"""Feature store access: Redis (online) and Cosmos DB (durable).

The online store answers point reads on the request path; the durable store
keeps every served arm and its reward so the retraining job can replay them.
"""

from __future__ import annotations

import os
from typing import Any

DEFAULT_FEATURES: dict[str, Any] = {"feature1": 0.5, "feature2": 1.2}


class FeatureStore:
    """Reads hot features from Redis and writes events to Cosmos DB.

    Both backends are injected lazily so the service can start, and unit tests
    can run, without either dependency being reachable.
    """

    def __init__(
        self,
        redis_url: str | None = None,
        cosmos_endpoint: str | None = None,
    ) -> None:
        self.redis_url = redis_url or os.getenv("REDIS_URL", "")
        self.cosmos_endpoint = cosmos_endpoint or os.getenv("COSMOS_ENDPOINT", "")
        self._redis: Any | None = None

    # -- online ---------------------------------------------------------
    def get_features(self, user_id: str) -> dict[str, Any]:
        """Return the feature vector for `user_id`.

        Falls back to the segment default when Redis is unreachable, so a store
        outage degrades the price instead of failing the request.
        """
        client = self._client()
        if client is None:
            return {"user_id": user_id, **DEFAULT_FEATURES}
        try:
            raw = client.hgetall(f"features:{user_id}")
        except Exception:  # noqa: BLE001 - a store outage must not 500 the API
            return {"user_id": user_id, **DEFAULT_FEATURES}
        if not raw:
            return {"user_id": user_id, **DEFAULT_FEATURES}
        return {"user_id": user_id, **raw}

    def set_features(self, user_id: str, features: dict[str, Any]) -> None:
        """Persist the feature vector for `user_id` in the online store."""
        client = self._client()
        if client is None:
            return
        client.hset(f"features:{user_id}", mapping=features)

    # -- durable --------------------------------------------------------
    def record_event(self, event: dict[str, Any]) -> None:
        """Append a served arm or reward event to the durable store.

        Placeholder: wire the Cosmos DB container client here.
        """
        # TODO: cosmos_client.get_database_client(...).get_container_client("events")
        raise NotImplementedError("Cosmos DB writer not implemented yet")

    # -- internals ------------------------------------------------------
    def _client(self) -> Any | None:
        """Lazily build the Redis client; return None when unavailable."""
        if self._redis is not None:
            return self._redis
        if not self.redis_url:
            return None
        try:
            import redis  # imported here so tests do not need a live client
        except ImportError:  # pragma: no cover
            return None
        self._redis = redis.from_url(self.redis_url, decode_responses=True)
        return self._redis


_STORE: FeatureStore | None = None


def get_store() -> FeatureStore:
    """Return the process-wide feature store instance."""
    global _STORE
    if _STORE is None:
        _STORE = FeatureStore()
    return _STORE


def get_features(user_id: str) -> dict[str, Any]:
    """Module-level convenience wrapper around `FeatureStore.get_features`."""
    return get_store().get_features(user_id)


def set_features(user_id: str, features: dict[str, Any]) -> None:
    """Module-level convenience wrapper around `FeatureStore.set_features`."""
    get_store().set_features(user_id, features)
