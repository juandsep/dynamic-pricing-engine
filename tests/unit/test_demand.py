"""A synthetic panel with a known elasticity: the fit has to recover it."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from dp.demand import fit_curves, fit_within, price_tiers, summarise

PRICES = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0)
MONTHS = 2


def panel_of(elasticity: float, product: str, intercept: float = 3.0) -> pd.DataFrame:
    """Demand that follows a log-log line exactly, so the fit is exact or wrong."""
    rows = [
        {
            "stock_code": product,
            "month": pd.Timestamp(2010, month, 1),
            "price": price,
            "units": math.exp(intercept + elasticity * math.log(price)),
            "invoices": 1,
        }
        for price in PRICES
        for month in range(1, MONTHS + 1)
    ]
    return pd.DataFrame(rows)


def test_fit_recovers_a_known_elasticity() -> None:
    panel = pd.concat(
        [panel_of(-1.5, "A", 3.0), panel_of(-1.5, "B", 5.0)], ignore_index=True
    )
    curves, dropped = fit_curves(panel)

    assert dropped == {"too_few_prices": 0, "too_few_observations": 0}
    assert list(curves["stock_code"]) == ["A", "B"]
    assert curves["price_points"].tolist() == [len(PRICES)] * 2
    assert curves["elasticity"].tolist() == pytest.approx([-1.5, -1.5], rel=1e-9)
    assert curves["r2"].tolist() == pytest.approx([1.0, 1.0], abs=1e-9)
    # Both months carry every price, so the curve fitted on the first predicts the second.
    assert curves["holdout_r2"].tolist() == pytest.approx([1.0, 1.0], abs=1e-9)


def test_pooled_fit_ignores_which_products_are_expensive() -> None:
    """Two products on opposite price levels, same elasticity: the intercept differs."""
    panel = pd.concat(
        [panel_of(-2.0, "CHEAP", 3.0), panel_of(-2.0, "PRICEY", 6.0)], ignore_index=True
    )
    slope, _, _ = fit_within(panel)
    assert slope == pytest.approx(-2.0, rel=1e-9), (
        "the intercept difference must not leak in"
    )


def test_products_without_price_variation_are_dropped_and_counted() -> None:
    no_variation = panel_of(-1.5, "FLAT").assign(price=2.0)  # one price, twelve rows
    too_few_rows = panel_of(-1.5, "THIN").head(7)  # four prices, seven rows
    panel = pd.concat(
        [panel_of(-1.5, "GOOD"), no_variation, too_few_rows], ignore_index=True
    )

    curves, dropped = fit_curves(panel)

    assert list(curves["stock_code"]) == ["GOOD"]
    assert dropped == {"too_few_prices": 1, "too_few_observations": 1}


def test_tiers_separate_elasticities_by_price_level() -> None:
    cheap = [panel_of(-0.5, f"CHEAP{i}") for i in range(3)]
    pricey = [panel_of(-2.5, f"PRICEY{i}") for i in range(3)]
    for factor, frame in zip((1, 2, 3, 10, 20, 30), cheap + pricey, strict=True):
        frame["price"] *= factor
    panel = pd.concat(cheap + pricey, ignore_index=True)

    tiers = price_tiers(panel)
    assert tiers["CHEAP0"] == "q1"  # cheapest product overall
    assert tiers["PRICEY2"] == "q4"  # dearest product overall

    curves, dropped = fit_curves(panel)
    summary = summarise(curves, panel, dropped)

    by_tier = summary["by_price_tier"]
    assert isinstance(by_tier, dict)
    assert by_tier["q1"]["elasticity"] == pytest.approx(-0.5, rel=1e-6)
    assert by_tier["q4"]["elasticity"] == pytest.approx(-2.5, rel=1e-6)
    # Equal log-price spread in both groups, so the pooled slope is their mean.
    assert summary["pooled"]["elasticity"] == pytest.approx(-1.5, rel=1e-6)
    assert summary["curves"]["share_negative"] == 1.0
