"""Pricing simulator on the F1 demand curves, and offline replay of a logged policy.

The real data has no propensities, so the counterfactual comes from a simulation: each
fitted curve becomes a product with a known conversion probability per price arm, every
policy is played against the same request stream, and a log with known propensities is
written in the `docs/data-contract.md` format.

    uv run python -m dp.simulate                    # simulate four policies, write a log
    uv run python -m dp.simulate --events log.jsonl --baseline-price 2.95   # replay a log

The ground truth here is the fitted curve, which is an upper bound on the causal
elasticity (prices were observational). The simulator measures whether a policy finds the
optimum of a known world; it does not claim that world is the real one.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from dp.data import DATA_DIR
from dp.demand import CURVES_PARQUET
from dp.thompson import CATALOGUE_PATH

# The data carries no costs (docs/data-contract.md, item 4), so margin needs an
# assumption: variable cost as a share of the price that sold the most units. Anchored
# there because a retailer does not sell most of its units at a loss; anchored on the
# median instead, 4 of the top 50 products had their usual price below cost.
COST_SHARE = 0.5
# Probability that a request converts at the product's median price. The curve gives
# the shape around it; the level is a choice, and it sets how many requests a policy
# needs before its posterior means anything.
BASE_CONVERSION = 0.05
N_ARMS = 5
LOG_JSONL = DATA_DIR / "processed" / "simulated_log.jsonl"

_IMPRESSION_KEYS = ("id", "ts", "user_id", "segment", "arm", "propensity")
_REWARD_KEYS = ("id", "ts", "impression_id", "converted", "margin", "window_hours")


def _require(row: dict[str, Any], keys: Iterable[str], line_no: int) -> None:
    missing = [k for k in keys if k not in row]
    if missing:
        raise ValueError(f"line {line_no}: missing {', '.join(missing)}")


def load_events(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse and validate the log. Raises ValueError on the first defect."""
    impressions: list[dict[str, Any]] = []
    rewards: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {line_no}: not JSON ({exc.msg})") from exc
            kind = row.get("type")
            if kind == "impression":
                _require(row, _IMPRESSION_KEYS, line_no)
                if not 0 < float(row["propensity"]) <= 1:
                    raise ValueError(f"line {line_no}: propensity must be in (0, 1]")
                impressions.append(row)
            elif kind == "reward":
                _require(row, _REWARD_KEYS, line_no)
                rewards.append(row)
            else:
                raise ValueError(f"line {line_no}: unknown type {kind!r}")
    return impressions, rewards


def attribute(
    impressions: list[dict[str, Any]], rewards: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    """Join rewards onto impressions.

    An impression with no reward inside its window is censored: it counts as
    `converted=False, margin=0.0` (docs/data-contract.md, *Attribution rules*). A second
    reward for the same impression is a producer defect, counted and ignored.
    """
    by_impression: dict[str, dict[str, Any]] = {}
    defects = 0
    for reward in rewards:
        key = str(reward["impression_id"])
        if key in by_impression:
            defects += 1
            continue
        by_impression[key] = reward

    joined: list[dict[str, Any]] = []
    for impression in impressions:
        reward = by_impression.get(str(impression["id"]))
        joined.append(
            {
                "arm": float(impression["arm"]),
                "segment": str(impression["segment"]),
                "propensity": float(impression["propensity"]),
                "converted": bool(reward["converted"]) if reward else False,
                "margin": float(reward["margin"]) if reward else 0.0,
            }
        )
    return joined, defects


def by_arm(rows: list[dict[str, Any]]) -> dict[float, dict[str, float]]:
    """Per-arm counts: served, converted, conversion rate and margin."""
    table: dict[float, dict[str, float]] = defaultdict(
        lambda: {"served": 0.0, "converted": 0.0, "margin": 0.0}
    )
    for row in rows:
        cell = table[row["arm"]]
        cell["served"] += 1
        cell["converted"] += 1 if row["converted"] else 0
        cell["margin"] += row["margin"]
    for cell in table.values():
        cell["rate"] = cell["converted"] / cell["served"]
    return dict(sorted(table.items()))


def snips(rows: list[dict[str, Any]], price: float) -> float | None:
    """Self-normalised propensity-weighted estimate of a fixed-price policy.

    Returns None when the log contains no impression where the policy would pick `price`
    (the estimate would be 0/0, not zero revenue).
    """
    weight_sum = 0.0
    weighted = 0.0
    for row in rows:
        if row["arm"] != price:
            continue
        weight = 1.0 / row["propensity"]
        weight_sum += weight
        weighted += weight * row["margin"]
    return None if weight_sum == 0 else weighted / weight_sum


def report(path: Path, baseline_price: float) -> None:
    impressions, rewards = load_events(path)
    rows, defects = attribute(impressions, rewards)
    table = by_arm(rows)

    print(f"log: {path}")
    print(
        f"impressions: {len(impressions)}  rewards: {len(rewards)}  defects: {defects}"
    )
    print(f"realised margin: {sum(r['margin'] for r in rows):.2f}")
    print()
    print(f"{'arm':>8} {'served':>7} {'conv':>6} {'rate':>7} {'margin':>9}")
    for arm, cell in table.items():
        print(
            f"{arm:>8g} {int(cell['served']):>7} {int(cell['converted']):>6} "
            f"{cell['rate']:>6.1%} {cell['margin']:>9.2f}"
        )

    starved = [arm for arm, cell in table.items() if cell["served"] < 30]
    print()
    if starved:
        print(
            f"starved arms (fewer than 30 impressions): {starved} — their rows are noise"
        )
    estimate = snips(rows, baseline_price)
    if estimate is None:
        print(
            f"baseline {baseline_price}: never served, no off-policy estimate possible"
        )
    else:
        print(
            f"baseline {baseline_price}: SNIPS estimate {estimate:.2f} per impression"
        )


@dataclass(frozen=True)
class World:
    """Products the policies price, each with a known conversion curve over its arms.

    Arrays are (products, arms). `arms` are absolute prices inside each product's
    observed band: a generic 1-100 arm would make the regret meaningless.
    """

    codes: list[str]
    arms: np.ndarray
    conversion: np.ndarray
    cost: np.ndarray
    modal_arm: np.ndarray

    @property
    def unit_margin(self) -> np.ndarray:
        return self.arms - self.cost[:, None]

    @property
    def expected(self) -> np.ndarray:
        """Expected margin per request for every (product, arm)."""
        return self.conversion * self.unit_margin

    @property
    def oracle_arm(self) -> np.ndarray:
        return self.expected.argmax(axis=1)


def build_world(
    curves: pd.DataFrame,
    n_arms: int = N_ARMS,
    cost_share: float = COST_SHARE,
    base_conversion: float = BASE_CONVERSION,
) -> World:
    """Turn fitted curves into products: q(p) = base * (p / median) ** elasticity."""
    low = curves["price_min"].to_numpy()
    high = curves["price_max"].to_numpy()
    median = curves["median_price"].to_numpy()
    arms = np.round(np.linspace(low, high, n_arms, axis=1), 2)
    elasticity = curves["elasticity"].to_numpy()[:, None]
    conversion = np.clip(base_conversion * (arms / median[:, None]) ** elasticity, 0, 1)
    modal = curves["modal_price"].to_numpy()[:, None]
    return World(
        codes=[str(code) for code in curves["stock_code"]],
        arms=arms,
        conversion=conversion,
        cost=cost_share * modal[:, 0],
        modal_arm=np.abs(arms - modal).argmin(axis=1),
    )


def load_world(curves: Path | str = CURVES_PARQUET, top: int = 50) -> World:
    """The `top` products by units sold: enough traffic per product for a demo."""
    return build_world(pd.read_parquet(curves).nlargest(top, "units"))


class Thompson:
    """Beta-Bernoulli posterior per (product, arm) on conversion; picks the arm whose
    sampled conversion times its unit margin is highest."""

    def __init__(self, world: World, rng: np.random.Generator) -> None:
        self.world = world
        self.rng = rng
        self.alpha = np.ones_like(world.arms)
        self.beta = np.ones_like(world.arms)

    def choose(self) -> np.ndarray:
        draw = self.rng.beta(self.alpha, self.beta)
        return (draw * self.world.unit_margin).argmax(axis=1)

    def update(self, arm: np.ndarray, converted: np.ndarray) -> None:
        rows = np.arange(len(arm))
        self.alpha[rows, arm] += converted
        self.beta[rows, arm] += ~converted

    def best_by_mean(self) -> np.ndarray:
        mean = self.alpha / (self.alpha + self.beta)
        return (mean * self.world.unit_margin).argmax(axis=1)


@dataclass
class Outcome:
    """What one policy earned over the run."""

    policy: str
    margin: float  # realised
    expected: float  # sum of the expected margin of every arm served
    regret: float  # oracle expected minus this policy's expected
    share_of_oracle: float
    pulls: np.ndarray  # (products, arms)
    settled_at: np.ndarray | None = None  # per product, requests until settled


def play(
    world: World,
    requests: int,
    seed: int = 0,
) -> dict[str, Outcome]:
    """Every policy faces the same requests: one per product per step, and the same
    uniform draw decides conversion, so differences come from the policy, not luck."""
    n_products, n_arms = world.arms.shape
    draws = np.random.default_rng(seed).random((requests, n_products))
    rows = np.arange(n_products)
    expected = world.expected
    oracle_total = expected[rows, world.oracle_arm].sum() * requests

    uniform_rng = np.random.default_rng(seed + 1)
    thompson = Thompson(world, np.random.default_rng(seed + 2))
    policies: dict[str, Callable[[], np.ndarray]] = {
        "oracle": lambda: world.oracle_arm,
        "modal": lambda: world.modal_arm,
        "uniform": lambda: uniform_rng.integers(n_arms, size=n_products),
        "thompson": thompson.choose,
    }

    outcomes: dict[str, Outcome] = {}
    for name, choose in policies.items():
        pulls = np.zeros((n_products, n_arms), dtype=int)
        margin = 0.0
        # Last step at which the posterior-mean best arm was not the oracle's.
        last_wrong = np.full(n_products, -1)
        for step in range(requests):
            arm = choose()
            converted = draws[step] < world.conversion[rows, arm]
            pulls[rows, arm] += 1
            margin += float((converted * world.unit_margin[rows, arm]).sum())
            if name == "thompson":
                thompson.update(arm, converted)
                wrong = thompson.best_by_mean() != world.oracle_arm
                last_wrong[wrong] = step
        earned = float((pulls * expected).sum())
        outcomes[name] = Outcome(
            policy=name,
            margin=margin,
            expected=earned,
            regret=oracle_total - earned,
            share_of_oracle=earned / oracle_total,
            pulls=pulls,
            settled_at=last_wrong + 1 if name == "thompson" else None,
        )
    return outcomes


def write_log(
    path: Path, world: World, requests: int, seed: int = 0, window_hours: int = 24
) -> int:
    """A uniform logging policy over each product's arms, so every propensity is
    exactly 1 / n_arms. Returns the number of impressions written."""
    rng = np.random.default_rng(seed)
    n_products, n_arms = world.arms.shape
    start = datetime(2026, 9, 1, tzinfo=UTC)
    count = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for step in range(requests):
            arm = rng.integers(n_arms, size=n_products)
            converted = (
                rng.random(n_products) < world.conversion[np.arange(n_products), arm]
            )
            for product in range(n_products):
                ts = start + timedelta(seconds=count)
                price = float(world.arms[product, arm[product]])
                impression = {
                    "type": "impression",
                    "schema_version": 2,
                    "id": f"i-{count}",
                    "ts": ts.isoformat().replace("+00:00", "Z"),
                    "user_id": f"u-{step}",
                    "segment": world.codes[product],
                    "arm": price,
                    "arm_index": int(arm[product]),
                    "propensity": 1 / n_arms,
                    "features": {},
                    "feature_version": 0,
                    "policy_version": "v0-uniform",
                }
                handle.write(json.dumps(impression) + "\n")
                if converted[product]:
                    reward = {
                        "type": "reward",
                        "schema_version": 2,
                        "id": f"r-{count}",
                        "ts": (ts + timedelta(hours=1))
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "impression_id": f"i-{count}",
                        "converted": True,
                        "margin": round(price - float(world.cost[product]), 4),
                        "window_hours": window_hours,
                    }
                    handle.write(json.dumps(reward) + "\n")
                count += 1
    return count


def write_catalogue(path: Path, world: World) -> None:
    """The arms and unit cost per product that the serving sampler prices from."""
    catalogue = {
        code: {"arms": world.arms[i].tolist(), "cost": round(float(world.cost[i]), 4)}
        for i, code in enumerate(world.codes)
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalogue, indent=2) + "\n", encoding="utf-8")


def simulate(
    curves: Path, top: int, requests: int, log: Path, log_requests: int
) -> None:
    world = load_world(curves, top)
    write_catalogue(CATALOGUE_PATH, world)
    outcomes = play(world, requests)
    n_products, n_arms = world.arms.shape
    print(
        f"{n_products} products x {n_arms} arms, {requests} requests per product, "
        f"cost {COST_SHARE:.0%} of modal price, base conversion {BASE_CONVERSION:.0%}"
    )
    print(
        f"oracle arm per product: {np.bincount(world.oracle_arm, minlength=n_arms)} "
        "(count by arm index, cheapest first)"
    )
    print()
    print(
        f"{'policy':<9} {'margin':>11} {'expected':>11} {'regret':>10} {'% oracle':>9}"
    )
    for o in outcomes.values():
        print(
            f"{o.policy:<9} {o.margin:>11.2f} {o.expected:>11.2f} "
            f"{o.regret:>10.2f} {o.share_of_oracle:>8.1%}"
        )
    settled = outcomes["thompson"].settled_at
    assert settled is not None
    done = settled[settled < requests]
    print()
    print(
        f"thompson settled on the oracle arm in {len(done)}/{n_products} products; "
        f"requests needed: median {np.median(done) if len(done) else float('nan'):.0f}, "
        f"p90 {np.quantile(done, 0.9) if len(done) else float('nan'):.0f}"
    )
    written = write_log(log, world, log_requests)
    print(f"uniform log: {written} impressions -> {log}")
    print(f"catalogue: {n_products} products -> {CATALOGUE_PATH}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Simulate pricing policies on the demand curves, or replay a log."
    )
    parser.add_argument(
        "--events", type=Path, help="replay this JSONL log instead of simulating"
    )
    parser.add_argument(
        "--baseline-price",
        type=float,
        default=50,
        help="replay: fixed price to evaluate against (default: 50)",
    )
    parser.add_argument("--curves", type=Path, default=CURVES_PARQUET)
    parser.add_argument("--top", type=int, default=50, help="products by units sold")
    parser.add_argument(
        "--requests", type=int, default=20_000, help="requests per product"
    )
    parser.add_argument("--log", type=Path, default=LOG_JSONL)
    parser.add_argument(
        "--log-requests", type=int, default=2_000, help="logged requests per product"
    )
    args = parser.parse_args(argv)
    if args.events is None:
        simulate(args.curves, args.top, args.requests, args.log, args.log_requests)
        return 0
    try:
        report(args.events, args.baseline_price)
    except ValueError as exc:
        print(f"invalid log: {exc}")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
