"""Export the event log from the store as JSONL, in the docs/data-contract.md format.

    uv run python -m dp.export data/processed/events.jsonl

Reads Cosmos DB when COSMOS_ENDPOINT is set (a cross-partition scan, so run it
offline), with whatever identity DefaultAzureCredential finds: the Azure CLI login on
a laptop. Cosmos system fields (`_rid`, `_ts`, ...) are dropped.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dp.store import Store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    args = parser.parse_args(argv)
    events = Store().events()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for event in sorted(events, key=lambda e: (e.get("ts", ""), e["id"])):
            clean = {k: v for k, v in event.items() if not k.startswith("_")}
            handle.write(json.dumps(clean) + "\n")
    kinds = {
        k: sum(e.get("type") == k for e in events) for k in ("impression", "reward")
    }
    print(json.dumps({"out": str(args.out), **kinds}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
