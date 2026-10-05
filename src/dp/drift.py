"""Drift between the traffic a policy was registered on and the traffic it serves.

Run: python -m dp.drift REFERENCE CURRENT

REFERENCE is the reference_profile.json that `python -m dp.retrain` registers next to
the catalogue. CURRENT is an impression log in the docs/data-contract.md format (an
export of the Cosmos `events` container, or a simulated log).

Two PSIs, both on categories, so there are no bin edges to choose:
- traffic mix: share of impressions per product. A product that starts dominating
  the traffic changes what the posterior learns from.
- served position: share of impressions per arm index (0 is the cheapest arm in a
  product's band, 4 the dearest). A policy that drifts toward one end of the band
  shows here before it shows in margin.
Above 0.2 is drift, the same threshold as the reference project.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np

from dp.simulate import load_events

DRIFT = 0.2
EPS = 1e-4  # an empty category would make PSI infinite


def _shares(counts: Counter[str]) -> dict[str, float]:
    total = sum(counts.values())
    return {key: n / total for key, n in counts.items()} if total else {}


def profile(impressions: Iterable[dict[str, Any]]) -> dict[str, dict[str, float]]:
    rows = list(impressions)
    return {
        "products": _shares(Counter(str(r["segment"]) for r in rows)),
        "arms": _shares(Counter(str(r["arm_index"]) for r in rows)),
    }


def profile_from_pulls(
    codes: list[str], pulls: np.ndarray
) -> dict[str, dict[str, float]]:
    """The same profile from a simulated run's (products, arms) pull counts."""
    total = float(pulls.sum())
    return {
        "products": {c: float(n) / total for c, n in zip(codes, pulls.sum(axis=1))},
        "arms": {str(i): float(n) / total for i, n in enumerate(pulls.sum(axis=0))},
    }


def psi(expected: dict[str, float], actual: dict[str, float]) -> float:
    keys = expected.keys() | actual.keys()
    e = np.clip([expected.get(k, 0.0) for k in keys], EPS, None)
    a = np.clip([actual.get(k, 0.0) for k in keys], EPS, None)
    return float(np.sum((a - e) * np.log(a / e)))


def report(reference: dict[str, Any], current: dict[str, Any]) -> dict[str, float]:
    return {dim: psi(reference[dim], current[dim]) for dim in ("products", "arms")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("reference", type=Path)
    parser.add_argument("current", type=Path, help="impression log (JSONL)")
    args = parser.parse_args(argv)

    reference = json.loads(args.reference.read_text(encoding="utf-8"))
    impressions, _ = load_events(args.current)
    for dim, value in report(reference, profile(impressions)).items():
        flag = "DRIFT" if value > DRIFT else "ok"
        print(f"{dim:<9} PSI {value:.3f}  {flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
