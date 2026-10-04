"""The F2 check: on a world with a known optimum, the oracle wins by construction and
Thompson converges to it within the sample budget."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from dp.simulate import attribute, build_world, load_events, play, snips, write_log

# Seed 7 is the slowest of seeds 0-19 to settle (6,321 requests): the thresholds
# below hold for all twenty, not for a lucky one.
REQUESTS = 10_000


def curves() -> pd.DataFrame:
    """Two products whose optimum is interior, at the edge, and away from the modal
    price, so a policy that ignores demand cannot get there by accident."""
    return pd.DataFrame(
        [
            {
                "stock_code": "ELASTIC",
                "elasticity": -3.0,
                "median_price": 2.0,
                "price_min": 1.0,
                "price_max": 3.0,
                "modal_price": 3.0,
                "units": 100,
            },
            {
                "stock_code": "INELASTIC",
                "elasticity": -0.8,
                "median_price": 2.0,
                "price_min": 1.0,
                "price_max": 3.0,
                "modal_price": 1.0,
                "units": 90,
            },
        ]
    )


@pytest.fixture(scope="module")
def world():
    return build_world(curves(), base_conversion=0.3)


@pytest.fixture(scope="module")
def outcomes(world):
    return play(world, REQUESTS, seed=7)


def test_arms_are_absolute_prices_inside_the_band(world) -> None:
    assert world.arms.tolist() == [[1.0, 1.5, 2.0, 2.5, 3.0]] * 2
    # Cost is half the median price; elasticity -3 puts the optimum at 1.5,
    # elasticity -0.8 pushes it to the top of the band.
    assert world.oracle_arm.tolist() == [1, 4]
    assert world.modal_arm.tolist() == [4, 0]


def test_oracle_wins_by_construction(outcomes) -> None:
    oracle = outcomes["oracle"].expected
    for name in ("modal", "uniform", "thompson"):
        assert outcomes[name].expected < oracle, name
        assert outcomes[name].regret > 0, name
    assert outcomes["oracle"].share_of_oracle == pytest.approx(1.0)


def test_thompson_converges_to_the_oracle_within_budget(world, outcomes) -> None:
    thompson = outcomes["thompson"]
    settled = thompson.settled_at
    assert settled is not None
    assert (settled < REQUESTS).all(), settled
    # Most of its traffic ends on the oracle arm, and it beats the baselines.
    on_oracle = thompson.pulls[np.arange(2), world.oracle_arm] / REQUESTS
    assert (on_oracle > 0.7).all(), on_oracle
    assert thompson.share_of_oracle > 0.95
    assert thompson.expected > outcomes["uniform"].expected
    assert thompson.expected > outcomes["modal"].expected


def test_uniform_log_propensities_recover_the_true_margin(tmp_path) -> None:
    """The log is only worth writing if off-policy estimates from it are right."""
    path = tmp_path / "log.jsonl"
    one_product = build_world(curves().head(1), base_conversion=0.3)
    written = write_log(path, one_product, requests=20_000, seed=3)
    assert written == 20_000

    impressions, rewards = load_events(path)
    rows, defects = attribute(impressions, rewards)
    assert defects == 0
    assert {row["propensity"] for row in rows} == {0.2}
    for arm in range(5):
        price = float(one_product.arms[0, arm])
        assert snips(rows, price) == pytest.approx(
            one_product.expected[0, arm], abs=0.02
        )
