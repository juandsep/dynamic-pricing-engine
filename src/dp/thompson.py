"""Thompson Sampling over each product's price arms.

A segment is a product (decision in `PLAN.md`, F2). Its arms are absolute prices inside
the product's observed band, read from the catalogue that `python -m dp.simulate` and
`python -m dp.retrain` write. The posterior is a Beta per arm on conversion; the sampler draws a conversion
rate per arm, multiplies by the arm's unit margin and serves the argmax.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from dp.store import Store

PRICE_MIN = float(os.getenv("PRICE_MIN", "0.01"))
PRICE_MAX = float(os.getenv("PRICE_MAX", "100"))
POLICY_VERSION = os.getenv("POLICY_VERSION", "v1-thompson")
# Impressions priced at random for a price test, as in docs/data-contract.md.
EXPERIMENT_VERSION = "v0-uniform"
# The arms the API serves. Versioned in git and shipped in the image, and registered
# in MLflow by `python -m dp.retrain`; the serving path never reads the registry.
CATALOGUE_PATH = Path(__file__).with_name("catalogue.json")
# Thompson has no closed-form probability of picking an arm, so the propensity the
# data contract asks for is the share of these draws that pick the served arm.
PROPENSITY_DRAWS = 1000


@dataclass(frozen=True)
class Quote:
    segment: str
    arm: int
    price: float
    propensity: float
    clamped: bool = False  # the arm fell outside PRICE_MIN..PRICE_MAX
    policy_version: str = POLICY_VERSION


def load_catalogue(path: Path | str) -> dict[str, dict[str, Any]]:
    """`{segment: {"arms": [prices], "cost": unit_cost}}`."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


class ThompsonSampler:
    def __init__(
        self,
        catalogue: dict[str, dict[str, Any]],
        store: Store,
        rng: np.random.Generator | None = None,
        price_range: tuple[float, float] = (PRICE_MIN, PRICE_MAX),
    ) -> None:
        if price_range[0] > price_range[1]:
            raise ValueError("PRICE_MIN must be less than or equal to PRICE_MAX")
        self.catalogue = catalogue
        self.store = store
        self.rng = rng or np.random.default_rng()
        self.min_price, self.max_price = price_range

    def _arms(self, segment: str) -> tuple[np.ndarray, np.ndarray]:
        entry = self.catalogue[segment]  # KeyError: unknown product
        arms = np.asarray(entry["arms"], dtype=float)
        return arms, arms - float(entry["cost"])

    def quote(self, segment: str) -> Quote:
        arms, margin = self._arms(segment)
        alpha, beta = self.store.posterior(segment, len(arms))
        draws = self.rng.beta(alpha, beta, size=(PROPENSITY_DRAWS, len(arms)))
        winners = (draws * margin).argmax(axis=1)
        arm = int(winners[0])
        price = float(np.clip(arms[arm], self.min_price, self.max_price))
        return Quote(
            segment=segment,
            arm=arm,
            price=price,
            propensity=float((winners == arm).mean()),
            clamped=price != float(arms[arm]),
        )

    def randomised(self, segment: str, user_id: str) -> Quote:
        """A uniformly random arm, fixed per (user, product): a customer who reloads
        sees the same price, and every arm has propensity exactly 1 / n_arms."""
        arms, _ = self._arms(segment)
        arm = _hash_unit(f"arm|{user_id}|{segment}") * len(arms)
        price = float(np.clip(arms[int(arm)], self.min_price, self.max_price))
        return Quote(
            segment=segment,
            arm=int(arm),
            price=price,
            propensity=1 / len(arms),
            clamped=price != float(arms[int(arm)]),
            policy_version=EXPERIMENT_VERSION,
        )

    def reward(self, segment: str, arm: int, converted: bool) -> None:
        arms, _ = self._arms(segment)
        if not 0 <= arm < len(arms):
            raise ValueError(f"{segment} has no arm {arm}")
        self.store.add_outcome(segment, arm, converted, len(arms))


def _hash_unit(key: str) -> float:
    """A stable number in [0, 1) for a key: the same user and product always land in
    the same bucket, across replicas and restarts."""
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big") / 2**64


def in_experiment(user_id: str, segment: str, share: float) -> bool:
    return _hash_unit(f"bucket|{user_id}|{segment}") < share
