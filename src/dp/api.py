"""FastAPI service for the dynamic pricing engine."""

from __future__ import annotations

from fastapi import FastAPI

from .store import get_store
from .thompson import ThompsonSampler

app = FastAPI(title="Dynamic Pricing Engine", version="0.1.0")

sampler = ThompsonSampler()


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe used by the container healthcheck."""
    return {"status": "ok"}


@app.get("/price")
async def get_price(user_id: str) -> dict[str, object]:
    """Return a price for `user_id`.

    The sampler draws from the posterior of every price arm; features come from
    the online feature store.
    """
    features = get_store().get_features(user_id)
    price = sampler.sample(user_id, features=features)
    return {"user_id": user_id, "price": price, "features": features}
