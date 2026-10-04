"""FastAPI service for the dynamic pricing engine."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from functools import cache

from fastapi import FastAPI, HTTPException

from .store import Store
from .thompson import ThompsonSampler, load_catalogue

app = FastAPI(title="Dynamic Pricing Engine", version="0.1.0")

CATALOGUE_PATH = "data/processed/catalogue.json"


@cache
def get_sampler() -> ThompsonSampler:
    """Built on the first request, so the app imports without a catalogue or a store."""
    path = os.getenv("CATALOGUE_PATH", CATALOGUE_PATH)
    catalogue = load_catalogue(path) if os.path.exists(path) else {}
    return ThompsonSampler(catalogue, Store())


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used by the container healthcheck."""
    return {"status": "ok"}


@app.get("/price")
def get_price(user_id: str, product: str) -> dict[str, object]:
    """Quote a price for `product` to `user_id` and log the impression.

    A lost impression does not fail the quote: the customer still gets a price, and
    the log only misses one row.
    """
    sampler = get_sampler()
    if product not in sampler.catalogue:
        raise HTTPException(status_code=404, detail=f"unknown product {product}")
    quote = sampler.quote(product)
    impression_id = f"i-{uuid.uuid4().hex}"
    sampler.store.record_event(
        {
            "type": "impression",
            "schema_version": 2,
            "id": impression_id,
            "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "user_id": user_id,
            "segment": product,
            "arm": quote.price,
            "arm_index": quote.arm,
            "propensity": quote.propensity,
            "features": {},
            "feature_version": 0,
            "policy_version": quote.policy_version,
        }
    )
    return {
        "user_id": user_id,
        "product": product,
        "price": quote.price,
        "impression_id": impression_id,
        "policy_version": quote.policy_version,
    }
