"""Price-response curves from the clean order lines.

Fits log(units) ~ log(price) so the slope is a product's own price elasticity:
how much its demand moves when its price moves. Two levels come out of it, a
curve per product and one pooled per price tier, and the F2 simulator is
calibrated on both.

The prices in this data were set by a retailer reacting to stock and season, not
assigned at random, so the slope is a demand shape to simulate against, not a
causal elasticity. Treat it as the prior the bandit explores around.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

import duckdb
import numpy as np
import pandas as pd

from dp.data import DATA_DIR, ORDERS_PARQUET

# A product needs real price variation before its slope means anything: four
# price points across at least twelve (product, month, price) observations.
MIN_PRICES = 4
MIN_OBSERVATIONS = 12

CURVES_PARQUET = DATA_DIR / "processed" / "demand_curves.parquet"
SUMMARY_JSON = DATA_DIR / "processed" / "demand_summary.json"

PANEL_SQL = """
    SELECT stock_code,
           date_trunc('month', invoice_ts) AS month,
           price,
           SUM(quantity) AS units,
           COUNT(DISTINCT invoice) AS invoices
    FROM read_parquet('{orders}')
    GROUP BY 1, 2, 3
"""


def build_panel(orders: Path | str = ORDERS_PARQUET) -> pd.DataFrame:
    """One row per (product, month, price): the unit the curves are fitted on."""
    con = duckdb.connect()
    panel = con.execute(PANEL_SQL.format(orders=orders)).df()
    con.close()
    return panel


def _fit(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    """Least squares on logs: returns slope, intercept, R²."""
    slope, intercept = np.polyfit(x, y, 1)
    residual = y - (slope * x + intercept)
    spread = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - float(residual @ residual) / spread if spread > 0 else float("nan")
    return float(slope), float(intercept), r2


def holdout_cut(panel: pd.DataFrame) -> pd.Timestamp:
    """Where the fit stops and the measurement starts."""
    return cast(pd.Timestamp, panel["month"].quantile(0.7))


def _holdout_r2(train: pd.DataFrame, test: pd.DataFrame) -> float:
    """R² of the curve fitted before the cut, measured on the months after it."""
    if len(train) < 2 or len(test) < 2 or train["price"].nunique() < 2:
        return float("nan")
    slope, intercept, _ = _fit(
        np.log(train["price"].to_numpy()), np.log(train["units"])
    )
    log_units: pd.Series = np.log(test["units"])
    residual = log_units.to_numpy() - (
        slope * np.log(test["price"].to_numpy()) + intercept
    )
    spread = float(((log_units - log_units.mean()) ** 2).sum())
    return 1.0 - float(residual @ residual) / spread if spread > 0 else float("nan")


def fit_curves(
    panel: pd.DataFrame,
    min_prices: int = MIN_PRICES,
    min_observations: int = MIN_OBSERVATIONS,
    cut: pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """One elasticity per product, keeping only products with price variation."""
    rows: list[dict[str, object]] = []
    dropped = {"too_few_prices": 0, "too_few_observations": 0}
    cut = holdout_cut(panel) if cut is None else cut

    for code, group in panel.groupby("stock_code", sort=False):
        price_points = int(group["price"].nunique())
        if price_points < min_prices:
            dropped["too_few_prices"] += 1
            continue
        if len(group) < min_observations:
            dropped["too_few_observations"] += 1
            continue
        slope, intercept, r2 = _fit(
            np.log(group["price"].to_numpy()), np.log(group["units"].to_numpy())
        )
        rows.append(
            {
                "stock_code": code,
                "observations": len(group),
                "price_points": price_points,
                "elasticity": slope,
                "intercept": intercept,
                "r2": r2,
                "holdout_r2": _holdout_r2(
                    group[group["month"] < cut], group[group["month"] >= cut]
                ),
                "median_price": float(group["price"].median()),
                "units": int(group["units"].sum()),
            }
        )

    return pd.DataFrame(rows), dropped


def fit_within(panel: pd.DataFrame) -> tuple[float, float, float]:
    """Elasticity pooled across products, each product keeping its own intercept.

    Without the own-intercept term the slope mostly measures which products are
    expensive rather than what happens when one changes price.
    """
    log_price: pd.Series = np.log(panel["price"])
    log_units: pd.Series = np.log(panel["units"])
    by_product = panel["stock_code"]
    centred_price = log_price - log_price.groupby(by_product).transform("mean")
    centred_units = log_units - log_units.groupby(by_product).transform("mean")
    return _fit(centred_price.to_numpy(), centred_units.to_numpy())


def price_tiers(panel: pd.DataFrame, bins: int = 4) -> pd.Series:
    """Label each product by the quartile of its median price, cheapest first.

    Prices cluster, so qcut can return fewer bins than asked for; the labels
    follow whatever it produced instead of assuming four.
    """
    median = panel.groupby("stock_code")["price"].median()
    binned = pd.qcut(median, bins, duplicates="drop")
    labels = [f"q{index + 1}" for index in range(binned.cat.categories.size)]
    return cast(pd.Series, binned.cat.rename_categories(labels))


def summarise(
    curves: pd.DataFrame, panel: pd.DataFrame, dropped: dict[str, int]
) -> dict[str, object]:
    """The numbers F2 needs, and the ones worth reading before trusting a curve."""
    elasticity = curves["elasticity"]
    pooled_slope, _, pooled_r2 = fit_within(panel)
    held_out = curves["holdout_r2"].dropna()

    by_tier: dict[str, dict[str, object]] = {}
    tiered = panel.assign(tier=panel["stock_code"].map(price_tiers(panel).to_dict()))
    for tier, group in tiered.groupby("tier", observed=True):
        slope, _, r2 = fit_within(group)
        by_tier[str(tier)] = {
            "elasticity": slope,
            "r2": r2,
            "observations": len(group),
            "products": int(group["stock_code"].nunique()),
        }

    return {
        "panel": {
            "observations": len(panel),
            "products": int(panel["stock_code"].nunique()),
        },
        "curves": {
            "fitted": len(curves),
            "dropped": dropped,
            "median_elasticity": float(elasticity.median()),
            "p25_elasticity": float(elasticity.quantile(0.25)),
            "p75_elasticity": float(elasticity.quantile(0.75)),
            "share_negative": float((elasticity < 0).mean()),
            "median_r2": float(curves["r2"].median()),
            "median_price_points": float(curves["price_points"].median()),
        },
        "pooled": {
            "elasticity": pooled_slope,
            "r2": pooled_r2,
            "observations": len(panel),
        },
        "holdout": {
            "cut": str(holdout_cut(panel)),
            "products": len(held_out),
            "median_r2": float(held_out.median()),
            "share_beating_the_mean": float((held_out > 0).mean()),
        },
        "by_price_tier": by_tier,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fit price-response curves from the clean order lines."
    )
    parser.add_argument("--orders", default=str(ORDERS_PARQUET))
    parser.add_argument("--curves", default=str(CURVES_PARQUET))
    parser.add_argument("--summary", default=str(SUMMARY_JSON))
    args = parser.parse_args(argv)

    panel = build_panel(args.orders)
    curves, dropped = fit_curves(panel)
    summary = summarise(curves, panel, dropped)

    Path(args.curves).parent.mkdir(parents=True, exist_ok=True)
    curves.to_parquet(args.curves, index=False)
    Path(args.summary).write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
