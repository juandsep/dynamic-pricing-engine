"""Read a randomised price test: the causal elasticity per product, and its size.

    uv run python -m dp.experiment --events log.jsonl
    uv run python -m dp.experiment --events log.jsonl --target-se 0.2

The F1 elasticities come from prices the retailer chose, so they are an upper bound.
When prices are assigned at random (the uniform logging policy, propensity 1/5 per
arm), the conversion rate at each price is an unbiased estimate, and the slope of
log(conversion) on log(price) across a product's arms is its causal elasticity.

For each product it prints that estimate, its standard error, the observational
elasticity next to it, and how many randomised requests the product needs for the
standard error to reach the target: the size of the test that would make the
simulated world a measured one.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from dp.simulate import attribute, load_events
from dp.thompson import EXPERIMENT_VERSION


def _fit(x: np.ndarray, n: np.ndarray, k: np.ndarray) -> tuple[float, float]:
    """Binomial GLM with a log link, log(p) = a + b * log(price), by Fisher scoring.

    Returns the slope and its standard error from the inverse Fisher information.
    Maximum likelihood needs no continuity correction, which would pull the slope
    toward zero on arms that sold little.
    """
    X = np.column_stack([np.ones_like(x), x])
    p = np.clip((k + 0.5) / (n + 1), 1e-6, 0.99)  # starting point only
    beta = np.linalg.lstsq(X, np.log(p), rcond=None)[0]
    for _ in range(50):
        mu = np.clip(np.exp(X @ beta), 1e-9, 1 - 1e-9)
        w = n * mu / (1 - mu)
        z = X @ beta + (k / n - mu) / mu
        info = X.T @ (w[:, None] * X)
        step = np.linalg.solve(info, X.T @ (w * z)) - beta
        beta = beta + step
        if np.max(np.abs(step)) < 1e-10:
            break
    mu = np.clip(np.exp(X @ beta), 1e-9, 1 - 1e-9)
    info = X.T @ ((n * mu / (1 - mu))[:, None] * X)
    return float(beta[1]), float(np.sqrt(np.linalg.inv(info)[1, 1]))


def estimate(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Causal elasticity per segment from randomised rows. Rows from a policy that
    chose prices on purpose give a biased slope."""
    cells: dict[str, dict[float, list[int]]] = defaultdict(
        lambda: defaultdict(lambda: [0, 0])
    )
    for row in rows:
        cell = cells[row["segment"]][float(row["arm"])]
        cell[0] += 1
        cell[1] += int(row["converted"])
    out = {}
    for segment, arms in cells.items():
        if len(arms) < 2:
            continue
        price = np.array(sorted(arms))
        n = np.array([arms[p][0] for p in price], dtype=float)
        k = np.array([arms[p][1] for p in price], dtype=float)
        slope, se = _fit(np.log(price), n, k)
        out[segment] = {"elasticity": slope, "se": se, "requests": int(n.sum())}
    return out


def requests_needed(se: float, requests: int, target_se: float) -> int:
    """The standard error shrinks with the square root of the sample."""
    return math.ceil(requests * (se / target_se) ** 2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--target-se", type=float, default=0.2)
    parser.add_argument(
        "--truth",
        type=Path,
        help="hidden curves from dp.shoppers, to check the estimate against",
    )
    parser.add_argument(
        "--observational",
        type=Path,
        default=Path("data/processed/demand_curves.parquet"),
        help="F1 curves, to compare against; skipped if missing",
    )
    args = parser.parse_args(argv)

    impressions, rewards = load_events(args.events)
    # Only randomised impressions identify the curve; the policy's own choices are
    # what the observational data already suffers from.
    total = len(impressions)
    impressions = [
        i
        for i in impressions
        if i.get("policy_version", EXPERIMENT_VERSION) == EXPERIMENT_VERSION
    ]
    if len(impressions) < total:
        print(f"read {len(impressions)} randomised impressions of {total}")
    if any(
        not math.isclose(float(i["propensity"]), float(impressions[0]["propensity"]))
        for i in impressions
    ):
        print(
            "warning: propensities differ, so assignment was not uniform; the slope may be biased"
        )
    rows, _ = attribute(impressions, rewards)
    estimates = estimate(rows)

    observed: dict[str, float] = {}
    if args.observational.exists():
        import pandas as pd

        curves = pd.read_parquet(args.observational).set_index("stock_code")
        observed = curves["elasticity"].to_dict()

    hidden: dict[str, float] = {}
    if args.truth:
        hidden = {
            code: t["elasticity"]
            for code, t in json.loads(args.truth.read_text(encoding="utf-8")).items()
        }

    header = f"{'product':<10} {'causal':>8} {'se':>6} {'observ.':>8}"
    header += f" {'hidden':>8} {'z':>6}" if hidden else ""
    print(header + f" {'requests':>9} {'needed':>8}")
    zs = []
    for segment, e in sorted(estimates.items(), key=lambda kv: -kv[1]["requests"]):
        needed = requests_needed(e["se"], e["requests"], args.target_se)
        obs = observed.get(segment)
        line = f"{segment:<10} {e['elasticity']:>8.2f} {e['se']:>6.2f} "
        line += f"{obs:>8.2f}" if obs is not None else f"{'-':>8}"
        if hidden:
            truth = hidden.get(segment)
            if truth is None:
                line += f" {'-':>8} {'-':>6}"
            else:
                zs.append((e["elasticity"] - truth) / e["se"])
                line += f" {truth:>8.2f} {zs[-1]:>6.2f}"
        print(line + f" {e['requests']:>9} {needed:>8}")
    summary: dict[str, Any] = {
        "products": len(estimates),
        "median_se": round(float(np.median([e["se"] for e in estimates.values()])), 3),
    }
    if zs:
        # Honest errors put about 95% of the truths within two standard errors.
        summary["within_2_se"] = f"{sum(abs(z) < 2 for z in zs)}/{len(zs)}"
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
