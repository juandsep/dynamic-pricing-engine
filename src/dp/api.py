"""FastAPI service for the dynamic pricing engine."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime
from functools import cache

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .store import Store
from .thompson import CATALOGUE_PATH, POLICY_VERSION, ThompsonSampler, load_catalogue

log = logging.getLogger(__name__)

app = FastAPI(title="Dynamic Pricing Engine", version="0.1.0")


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(ts: datetime) -> str:
    return ts.isoformat().replace("+00:00", "Z")


@cache
def get_sampler() -> ThompsonSampler:
    """Built on the first request, so the app imports without a catalogue or a store."""
    path = os.getenv("CATALOGUE_PATH", str(CATALOGUE_PATH))
    catalogue = load_catalogue(path) if os.path.exists(path) else {}
    return ThompsonSampler(catalogue, Store())


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used by the container healthcheck."""
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, object]:
    """Readiness: the policy that would serve, and 503 while there is nothing to price."""
    products = len(get_sampler().catalogue)
    if not products:
        raise HTTPException(status_code=503, detail="no catalogue loaded")
    return {"status": "ready", "policy_version": POLICY_VERSION, "products": products}


@app.get("/price")
def get_price(user_id: str, product: str) -> dict[str, object]:
    """Quote a price for `product` to `user_id` and log the impression.

    A lost impression does not fail the quote: the customer still gets a price, and
    the log only misses one row (and a reward for it will be rejected as unknown).
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
            "ts": _iso(_now()),
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


class Reward(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    impression_id: str = Field(min_length=1, max_length=64)
    converted: bool
    margin: float = Field(ge=0)
    window_hours: int = Field(default=24, gt=0, le=24 * 30)


@app.post("/reward")
def post_reward(reward: Reward) -> dict[str, object]:
    """Attribute an outcome to a served impression (docs/data-contract.md).

    Idempotent by reward id: a retry answers 200 without moving the posterior again.
    An impression that was never served is a 404. When the outcome cannot be persisted
    the answer is 503, never a silent 200: a lost outcome degrades learning, a false
    success corrupts it.
    """
    store = get_sampler().store
    try:
        impression = store.event(reward.impression_id)
    except Exception:  # the store is down: nothing was written
        log.exception("reward %s: store unreachable", reward.id)
        raise HTTPException(status_code=503, detail="store unavailable") from None
    if impression is None or impression.get("type") != "impression":
        raise HTTPException(status_code=404, detail="impression was never served")

    now = _now()
    served = datetime.fromisoformat(impression["ts"])
    on_time = (now - served).total_seconds() <= reward.window_hours * 3600
    event = {
        "type": "reward",
        "schema_version": 2,
        **reward.model_dump(),
        "ts": _iso(now),
        "margin": reward.margin if reward.converted else 0.0,
    }
    # Claiming the reward id first is what makes a retry a duplicate. If the posterior
    # update then fails, the claim is removed so the retry applies it.
    try:
        if not store.claim(event):
            return {"id": reward.id, "duplicate": True, "applied": False}
    except Exception:
        log.exception("reward %s: not persisted", reward.id)
        raise HTTPException(status_code=503, detail="reward not persisted") from None
    if on_time:  # late rewards are stored, and replayed by retraining, not applied now
        try:
            get_sampler().reward(
                impression["segment"], impression["arm_index"], reward.converted
            )
        except Exception:
            log.exception("reward %s: posterior not updated", reward.id)
            try:
                store.delete_event(reward.id)
            except Exception:
                # ponytail: the event stays without its update, so this one outcome is
                # lost to the live posterior; retraining replays it. A transactional
                # batch per segment would close the gap if it ever matters.
                log.exception("reward %s: could not roll back the event", reward.id)
            raise HTTPException(
                status_code=503, detail="posterior not updated"
            ) from None
    return {"id": reward.id, "duplicate": False, "applied": on_time}
