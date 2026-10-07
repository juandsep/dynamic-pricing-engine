"""Write demo/data.json from the fitted curves: the simulated world per product and
how each policy did on it. Run after `python -m dp.demand`:

    uv run python demo/make_data.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from dp.demand import CURVES_PARQUET
from dp.simulate import BASE_CONVERSION, COST_SHARE, load_world, play

REQUESTS = 20_000
TOP = 50


def main() -> None:
    world = load_world(top=TOP)
    outcomes = play(world, REQUESTS)
    thompson = outcomes["thompson"]
    oracle_step = outcomes["oracle"].by_step[0]
    # Log-spaced checkpoints: the interesting part of a learning curve is the start.
    steps = np.unique(np.geomspace(10, REQUESTS, 48).astype(int))
    curve = {
        name: [round(float(o.by_step[:t].sum() / (oracle_step * t)), 4) for t in steps]
        for name, o in outcomes.items()
    }
    curves = pd.read_parquet(CURVES_PARQUET).set_index("stock_code")
    settled = thompson.settled_at
    products = [
        {
            "code": code,
            "elasticity": round(float(curves.loc[code, "elasticity"]), 2),
            "units": int(curves.loc[code, "units"]),
            "arms": world.arms[i].round(2).tolist(),
            "expected": world.expected[i].round(4).tolist(),
            "thompson_share": (thompson.pulls[i] / REQUESTS).round(4).tolist(),
            "oracle": int(world.oracle_arm[i]),
            "modal": int(world.modal_arm[i]),
            "settled_at": int(settled[i]) if settled[i] < REQUESTS else None,
        }
        for i, code in enumerate(world.codes)
    ]
    done = settled[settled < REQUESTS]
    data = {
        "requests_per_product": REQUESTS,
        "products_count": TOP,
        "cost_share": COST_SHARE,
        "base_conversion": BASE_CONVERSION,
        "policies": [
            {"policy": o.policy, "share_of_oracle": round(o.share_of_oracle, 4)}
            for o in outcomes.values()
        ],
        "margin_vs_modal": round(thompson.expected / outcomes["modal"].expected - 1, 4),
        "settled": {
            "products": len(done),
            "median_requests": round(float(np.median(done))),
        },
        "usual_is_best": int((world.modal_arm == world.oracle_arm).sum()),
        "curve": {"steps": steps.tolist(), "share_of_oracle": curve},
        "products": products,
    }
    out = Path(__file__).with_name("data.json")
    out.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
