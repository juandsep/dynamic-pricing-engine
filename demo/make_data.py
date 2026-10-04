"""Write demo/data.json from the fitted curves: the simulated world per product and
how each policy did on it. Run after `python -m dp.demand`:

    uv run python demo/make_data.py
"""

from __future__ import annotations

import json
from pathlib import Path

from dp.simulate import BASE_CONVERSION, COST_SHARE, load_world, play

REQUESTS = 20_000


def main() -> None:
    world = load_world()
    outcomes = play(world, REQUESTS)
    thompson = outcomes["thompson"]
    products = [
        {
            "code": code,
            "arms": world.arms[i].round(2).tolist(),
            "expected": world.expected[i].round(4).tolist(),
            "thompson_share": (thompson.pulls[i] / REQUESTS).round(4).tolist(),
            "oracle": int(world.oracle_arm[i]),
            "modal": int(world.modal_arm[i]),
        }
        for i, code in enumerate(world.codes)
    ]
    data = {
        "requests_per_product": REQUESTS,
        "cost_share": COST_SHARE,
        "base_conversion": BASE_CONVERSION,
        "policies": [
            {"policy": o.policy, "share_of_oracle": round(o.share_of_oracle, 4)}
            for o in outcomes.values()
        ],
        "products": products,
    }
    out = Path(__file__).with_name("data.json")
    out.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
