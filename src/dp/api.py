"""FastAPI service for the dynamic pricing engine."""

from __future__ import annotations

import logging
import os
import secrets
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from fastapi.security import APIKeyHeader
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field

from .store import Store
from .thompson import CATALOGUE_PATH, POLICY_VERSION, ThompsonSampler, load_catalogue

log = logging.getLogger(__name__)

app = FastAPI(title="Dynamic Pricing Engine", version="0.1.0")

# The only secret: callers of /price and /reward are servers (checkout, order
# system), never browsers. Without it anyone could post rewards and steer prices.
API_KEY = os.getenv("API_KEY", "")
RATE_LIMIT_RPS = float(os.getenv("RATE_LIMIT_RPS", "20"))
MAX_BODY_BYTES = int(os.getenv("MAX_BODY_BYTES", "4096"))

# Per instance: Prometheus scrapes each replica and sums across them.
LATENCY = Histogram(
    "dp_request_seconds",
    "Request latency",
    ["path", "status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5),
)
REJECTED = Counter("dp_rejected", "Requests refused before pricing", ["reason"])
SERVED = Counter("dp_prices_served", "Prices quoted", ["policy_version"])
CLAMPED = Counter(
    "dp_price_guard_clamped", "Quotes whose arm fell outside PRICE_MIN..PRICE_MAX"
)
REWARDS = Counter("dp_rewards", "Rewards received", ["outcome"])
# Fixed label set: raw paths from scanners would blow up the series count.
_PATHS = {"/price", "/reward", "/ready", "/health", "/metrics"}


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(ts: datetime) -> str:
    return ts.isoformat().replace("+00:00", "Z")


_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(key: str | None = Depends(_api_key_header)) -> None:
    """Fails closed: no key configured means no prices and no rewards."""
    if not API_KEY:
        log.error("API_KEY is not set: refusing to serve")
        REJECTED.labels("no_api_key_configured").inc()
        raise HTTPException(status_code=503, detail="service unavailable")
    if key is None or not secrets.compare_digest(key, API_KEY):
        REJECTED.labels("unauthorized").inc()
        raise HTTPException(status_code=401, detail="invalid API key")


class TokenBucket:
    """Requests per second with a burst of the same size. Thread-safe."""

    def __init__(self, rate: float) -> None:
        self.rate = rate
        self.tokens = rate
        self.last = time.monotonic()
        self.lock = threading.Lock()

    def take(self) -> bool:
        with self.lock:
            now = time.monotonic()
            self.tokens = min(self.rate, self.tokens + (now - self.last) * self.rate)
            self.last = now
            if self.tokens < 1:
                return False
            self.tokens -= 1
            return True


# ponytail: one bucket per instance, not per caller: there is one API key. The
# global cap is RATE_LIMIT_RPS x max replicas; per-key buckets (or API Management)
# when callers get their own keys.
_bucket = TokenBucket(RATE_LIMIT_RPS)


def rate_limit() -> None:
    if RATE_LIMIT_RPS > 0 and not _bucket.take():
        REJECTED.labels("rate_limited").inc()
        raise HTTPException(
            status_code=429, detail="rate limit exceeded", headers={"Retry-After": "1"}
        )


# Auth first: unauthenticated calls must not drain the bucket.
GUARDED = [Depends(require_api_key), Depends(rate_limit)]


@app.middleware("http")
async def reject_oversized_body(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Reject oversized bodies before anything parses them."""
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            too_big = int(declared) > MAX_BODY_BYTES
        except ValueError:
            return JSONResponse(
                status_code=400, content={"detail": "bad content-length"}
            )
        if too_big:
            REJECTED.labels("payload_too_large").inc()
            return JSONResponse(
                status_code=413, content={"detail": "payload too large"}
            )
    return await call_next(request)


@app.middleware("http")
async def record_latency(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    start = time.perf_counter()
    response = await call_next(request)
    path = request.url.path if request.url.path in _PATHS else "other"
    LATENCY.labels(path, str(response.status_code)).observe(time.perf_counter() - start)
    return response


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


@app.get("/metrics")
def metrics() -> Response:
    # ponytail: unauthenticated like /health; put it behind the API key or an internal
    # port if anything sensitive is ever labelled in it.
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/ready")
def ready() -> dict[str, object]:
    """Readiness: the policy that would serve, and 503 while there is nothing to price."""
    products = len(get_sampler().catalogue)
    if not products:
        raise HTTPException(status_code=503, detail="no catalogue loaded")
    return {"status": "ready", "policy_version": POLICY_VERSION, "products": products}


Id = Annotated[str, Query(min_length=1, max_length=64)]


@app.get("/price", dependencies=GUARDED)
def get_price(user_id: Id, product: Id) -> dict[str, object]:
    """Quote a price for `product` to `user_id` and log the impression.

    A lost impression does not fail the quote: the customer still gets a price, and
    the log only misses one row (and a reward for it will be rejected as unknown).
    """
    sampler = get_sampler()
    if product not in sampler.catalogue:
        raise HTTPException(status_code=404, detail=f"unknown product {product}")
    quote = sampler.quote(product)
    SERVED.labels(quote.policy_version).inc()
    if quote.clamped:
        CLAMPED.inc()
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


@app.post("/reward", dependencies=GUARDED)
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
        REWARDS.labels("failed").inc()
        raise HTTPException(status_code=503, detail="store unavailable") from None
    if impression is None or impression.get("type") != "impression":
        REWARDS.labels("unknown_impression").inc()
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
            REWARDS.labels("duplicate").inc()
            return {"id": reward.id, "duplicate": True, "applied": False}
    except Exception:
        log.exception("reward %s: not persisted", reward.id)
        REWARDS.labels("failed").inc()
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
            REWARDS.labels("failed").inc()
            raise HTTPException(
                status_code=503, detail="posterior not updated"
            ) from None
    REWARDS.labels("applied" if on_time else "late").inc()
    return {"id": reward.id, "duplicate": False, "applied": on_time}
