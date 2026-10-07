"""Rebuild every product's posterior from the event log.

    uv run python -m dp.rebuild                  # from Cosmos (COSMOS_ENDPOINT), dry run
    uv run python -m dp.rebuild --events x.jsonl # from an export, dry run
    uv run python -m dp.rebuild --write          # replace the posteriors in the store

The live posterior moves one reward at a time, and two kinds of outcome never reach it:
rewards that arrived after their window (stored, not applied, docs/data-contract.md) and
rewards whose update failed after the claim could not be rolled back. The log has them
all, so the posterior it implies is the authoritative one. Each impression counts once,
with the data contract's censoring: no reward means not converted.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from dp.simulate import attribute, load_events
from dp.store import Store
from dp.thompson import CATALOGUE_PATH, load_catalogue


def rebuild(
    impressions: Iterable[dict[str, Any]],
    rewards: Iterable[dict[str, Any]],
    catalogue: dict[str, dict[str, Any]],
) -> tuple[dict[str, tuple[list[float], list[float]]], int]:
    """Beta(1 + conversions, 1 + misses) per product and arm, from the uniform prior.
    Returns the posteriors and how many impressions fell outside the catalogue."""
    rows, _ = attribute(list(impressions), list(rewards))
    posteriors = {
        segment: ([1.0] * len(entry["arms"]), [1.0] * len(entry["arms"]))
        for segment, entry in catalogue.items()
    }
    skipped = 0
    for row in rows:
        arm = row["arm_index"]
        if row["segment"] not in posteriors or arm is None:
            skipped += 1
            continue
        alpha, beta = posteriors[row["segment"]]
        if not 0 <= arm < len(alpha):
            skipped += 1
            continue
        (alpha if row["converted"] else beta)[arm] += 1
    return posteriors, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--events", type=Path, help="JSONL export instead of the store")
    parser.add_argument("--catalogue", type=Path, default=CATALOGUE_PATH)
    parser.add_argument("--write", action="store_true", help="replace the posteriors")
    args = parser.parse_args(argv)

    store = Store()
    if args.events:
        impressions, rewards = load_events(args.events)
    else:
        events = store.events()
        impressions = [e for e in events if e.get("type") == "impression"]
        rewards = [e for e in events if e.get("type") == "reward"]
    posteriors, skipped = rebuild(impressions, rewards, load_catalogue(args.catalogue))

    observed = {
        s: p for s, p in posteriors.items() if sum(p[0]) + sum(p[1]) > 2 * len(p[0])
    }
    print(
        json.dumps(
            {
                "impressions": len(impressions),
                "rewards": len(rewards),
                "outside_catalogue": skipped,
                "products_with_traffic": len(observed),
            }
        )
    )
    if args.write:
        # ponytail: a rebuild replaces documents that live rewards also patch, so an
        # outcome applied between the scan and the write is lost to the live posterior
        # (it stays in the log for the next rebuild). Run it with traffic paused, or
        # compare etags if it ever has to run hot.
        for segment, (alpha, beta) in observed.items():
            store.put_posterior(segment, alpha, beta)
        print(f"wrote {len(observed)} posteriors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
