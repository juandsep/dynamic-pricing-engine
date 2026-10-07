"""Synthetic shoppers for a price test against a running API.

    API_KEY=... uv run python -m dp.shoppers https://<app> --products 10 --requests 2000

There is no store behind this project, so the customers are simulated, and what is
real is everything around them: the deployed API, its random assignment and
propensities, Cosmos DB, the export and the analysis. Each shopper asks `/price` for
a product, buys with the probability a hidden demand curve gives at that price, and
reports a purchase to `/reward`.

The hidden curve is deliberately not the one fitted on the data: its elasticity is
the observational one times `--factor` (0.6 by default, so less price-sensitive), as
it would be if the retailer's prices had moved with demand. Reading the test with
`dp.experiment` should recover the hidden elasticity, not the observational one; the
truth is written next to the run so the comparison can be checked.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
import urllib.error
import urllib.request
import zlib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from dp.demand import CURVES_PARQUET
from dp.thompson import CATALOGUE_PATH, load_catalogue

TRUTH_JSON = Path("data/processed/shopper_truth.json")
# Higher than the simulator's 5%: a test needs sales on every arm to read a slope,
# and the smaller the conversion rate, the more requests it takes.
BASE_CONVERSION = 0.2

Send = Callable[[str, str, dict[str, Any] | None], tuple[int, dict[str, Any]]]


def hidden_truth(
    products: list[str], curves: Any, factor: float, base: float
) -> dict[str, dict[str, float]]:
    return {
        code: {
            "elasticity": float(curves.loc[code, "elasticity"]) * factor,
            "observational": float(curves.loc[code, "elasticity"]),
            "median_price": float(curves.loc[code, "median_price"]),
            "base_conversion": base,
        }
        for code in products
    }


def buy_probability(truth: dict[str, float], price: float) -> float:
    ratio = price / truth["median_price"]
    return min(1.0, truth["base_conversion"] * ratio ** truth["elasticity"])


def http_sender(url: str, key: str) -> Send:
    def send(method: str, path: str, body: dict[str, Any] | None) -> tuple[int, dict]:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"X-API-Key": key, "content-type": "application/json"}
        req = urllib.request.Request(
            url + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, {}
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            # A dropped connection is one failed shopper, not the end of the test.
            return 0, {}

    return send


def run(
    send: Send,
    truth: dict[str, dict[str, float]],
    costs: dict[str, float],
    requests: int,
    rps: float = 15,
    workers: int = 8,
    seed: int = 0,
    start: int = 0,
) -> dict[str, int]:
    """`requests` shoppers per product, interleaved, at about `rps` per second.
    Shopper ids start at `start`, so a resumed run brings new customers."""
    jobs = [(i, code) for i in range(start, start + requests) for code in truth]
    stats = {"served": 0, "bought": 0, "throttled": 0, "failed": 0}
    lock = threading.Lock()
    interval = workers / rps if rps else 0.0

    def shop(job: tuple[int, str]) -> None:
        i, code = job
        rng = np.random.default_rng([seed, i, zlib.crc32(code.encode())])
        start = time.monotonic()
        for _ in range(5):  # retry a 429 after the Retry-After second
            status, quote = send(
                "GET", f"/price?user_id=shopper-{i}&product={code}", None
            )
            if status != 429:
                break
            with lock:
                stats["throttled"] += 1
            time.sleep(1)
        if status != 200:
            with lock:
                stats["failed"] += 1
            return
        bought = rng.random() < buy_probability(truth[code], quote["price"])
        if bought:
            body = {
                "id": f"r-{quote['impression_id']}",
                "impression_id": quote["impression_id"],
                "converted": True,
                "margin": round(max(quote["price"] - costs[code], 0.0), 4),
            }
            status, _ = send("POST", "/reward", body)
        with lock:
            stats["served"] += 1
            stats["bought"] += int(bought and status == 200)
        time.sleep(max(0.0, interval - (time.monotonic() - start)))

    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(shop, jobs))
    return stats


def main(argv: list[str] | None = None) -> int:
    import pandas as pd

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url")
    parser.add_argument("--products", type=int, default=10)
    parser.add_argument("--requests", type=int, default=2_000, help="per product")
    parser.add_argument("--factor", type=float, default=0.6)
    parser.add_argument("--rps", type=float, default=15)
    parser.add_argument("--start", type=int, default=0, help="first shopper id")
    parser.add_argument("--truth", type=Path, default=TRUTH_JSON)
    args = parser.parse_args(argv)

    catalogue = load_catalogue(CATALOGUE_PATH)
    products = list(catalogue)[: args.products]
    curves = pd.read_parquet(CURVES_PARQUET).set_index("stock_code")
    truth = hidden_truth(products, curves, args.factor, BASE_CONVERSION)
    args.truth.parent.mkdir(parents=True, exist_ok=True)
    args.truth.write_text(json.dumps(truth, indent=2) + "\n", encoding="utf-8")

    send = http_sender(args.url.rstrip("/"), os.environ["API_KEY"])
    costs = {code: float(catalogue[code]["cost"]) for code in products}
    stats = run(send, truth, costs, args.requests, rps=args.rps, start=args.start)
    print(json.dumps({**stats, "products": len(products), "truth": str(args.truth)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
