"""Offline replay of a logged pricing policy.

Reads a JSONL log of impressions and rewards (see `docs/data-contract.md`) and reports
what the logged policy actually earned, plus a propensity-weighted estimate of what a
fixed-price policy would have earned on the same traffic.

    uv run python -m dp.simulate --events log.jsonl --baseline-price 25

Stdlib only: this is a report over a file, not a pipeline.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

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
                "arm": int(impression["arm"]),
                "segment": str(impression["segment"]),
                "propensity": float(impression["propensity"]),
                "converted": bool(reward["converted"]) if reward else False,
                "margin": float(reward["margin"]) if reward else 0.0,
            }
        )
    return joined, defects


def by_arm(rows: list[dict[str, Any]]) -> dict[int, dict[str, float]]:
    """Per-arm counts: served, converted, conversion rate and margin."""
    table: dict[int, dict[str, float]] = defaultdict(
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


def snips(rows: list[dict[str, Any]], price: int) -> float | None:
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


def report(path: Path, baseline_price: int) -> None:
    impressions, rewards = load_events(path)
    rows, defects = attribute(impressions, rewards)
    table = by_arm(rows)

    print(f"log: {path}")
    print(
        f"impressions: {len(impressions)}  rewards: {len(rewards)}  defects: {defects}"
    )
    print(f"realised margin: {sum(r['margin'] for r in rows):.2f}")
    print()
    print(f"{'arm':>4} {'served':>7} {'conv':>6} {'rate':>7} {'margin':>9}")
    for arm, cell in table.items():
        print(
            f"{arm:>4} {int(cell['served']):>7} {int(cell['converted']):>6} "
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay a logged pricing policy and estimate a fixed-price baseline."
    )
    parser.add_argument(
        "--events", type=Path, required=True, help="JSONL log to replay"
    )
    parser.add_argument(
        "--baseline-price",
        type=int,
        default=50,
        help="fixed price to evaluate against (default: 50)",
    )
    args = parser.parse_args(argv)
    try:
        report(args.events, args.baseline_price)
    except ValueError as exc:
        print(f"invalid log: {exc}")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
