"""Posterior and event store: Azure Cosmos DB, or an in-memory stand-in.

With `COSMOS_ENDPOINT` set, two containers in the `COSMOS_DATABASE` database hold the
state, both partitioned on `/id`:

- `posteriors`: one document per segment (product) with its arms inside,
  `{"id": segment, "alpha": [...], "beta": [...]}`. A reward is one atomic `incr`
  patch, so concurrent replicas cannot lose an update.
- `events`: impressions and rewards from `docs/data-contract.md`, append-only.

Without it, the same code runs against `MemoryContainer`, so the service and the test
suite need no credentials and make no network call. The Cosmos client is built on first
use, never at import, and authenticates with `DefaultAzureCredential` (the managed
identity in Azure, no keys).
"""

from __future__ import annotations

import copy
import logging
import os
from typing import Any

from azure.cosmos.exceptions import (
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)

log = logging.getLogger(__name__)

CONTAINERS = ("posteriors", "events")


class MemoryContainer:
    """The slice of `azure.cosmos.ContainerProxy` the store uses, kept in a dict."""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}

    def read_item(self, item: str, partition_key: str) -> dict[str, Any]:
        if item not in self.items:
            raise CosmosResourceNotFoundError(message=f"{item} not found")
        return copy.deepcopy(self.items[item])

    def create_item(self, body: dict[str, Any]) -> dict[str, Any]:
        if body["id"] in self.items:
            raise CosmosResourceExistsError(message=f"{body['id']} exists")
        self.items[body["id"]] = copy.deepcopy(body)
        return body

    def upsert_item(self, body: dict[str, Any]) -> dict[str, Any]:
        self.items[body["id"]] = copy.deepcopy(body)
        return body

    def query_items(self, query: str, **_: Any) -> list[dict[str, Any]]:
        assert query == "SELECT * FROM c", query  # the only query the store issues
        return [copy.deepcopy(item) for item in self.items.values()]

    def delete_item(self, item: str, partition_key: str) -> None:
        if self.items.pop(item, None) is None:
            raise CosmosResourceNotFoundError(message=f"{item} not found")

    def patch_item(
        self, item: str, partition_key: str, patch_operations: list[dict[str, Any]]
    ) -> dict[str, Any]:
        doc = self.items.get(item)
        if doc is None:
            raise CosmosResourceNotFoundError(message=f"{item} not found")
        for operation in patch_operations:
            assert operation["op"] == "incr", operation
            _, field, index = operation["path"].split("/")
            doc[field][int(index)] += operation["value"]
        return copy.deepcopy(doc)


class Store:
    """Reads and updates posteriors, and appends events."""

    def __init__(
        self,
        endpoint: str | None = None,
        database: str | None = None,
        containers: dict[str, Any] | None = None,
    ) -> None:
        self.endpoint = (
            os.getenv("COSMOS_ENDPOINT", "") if endpoint is None else endpoint
        )
        self.database = database or os.getenv("COSMOS_DATABASE", "pricing")
        if containers is None and not self.endpoint:
            containers = {name: MemoryContainer() for name in CONTAINERS}
        self._containers = containers

    def _container(self, name: str) -> Any:
        if self._containers is None:
            from azure.cosmos import CosmosClient
            from azure.identity import DefaultAzureCredential

            client = CosmosClient(self.endpoint, credential=DefaultAzureCredential())
            db = client.get_database_client(self.database)
            self._containers = {n: db.get_container_client(n) for n in CONTAINERS}
        return self._containers[name]

    def posterior(self, segment: str, n_arms: int) -> tuple[list[float], list[float]]:
        """Beta parameters per arm. Uniform prior when the segment has no document,
        and also when the store is unreachable: an outage degrades the price to
        exploration instead of failing the request."""
        try:
            doc = self._container("posteriors").read_item(
                segment, partition_key=segment
            )
        except CosmosResourceNotFoundError:
            return [1.0] * n_arms, [1.0] * n_arms
        except Exception:  # fail open on the request path
            log.exception("posterior read failed for %s; serving the prior", segment)
            return [1.0] * n_arms, [1.0] * n_arms
        return doc["alpha"], doc["beta"]

    def add_outcome(self, segment: str, arm: int, converted: bool, n_arms: int) -> None:
        """Count one outcome on one arm. Raises when it cannot be persisted, so the
        caller can answer 503 instead of pretending the posterior moved."""
        container = self._container("posteriors")
        field = "alpha" if converted else "beta"
        operation = [{"op": "incr", "path": f"/{field}/{arm}", "value": 1}]
        try:
            container.patch_item(
                segment, partition_key=segment, patch_operations=operation
            )
            return
        except CosmosResourceNotFoundError:
            pass
        try:
            container.create_item(
                {"id": segment, "alpha": [1.0] * n_arms, "beta": [1.0] * n_arms}
            )
        except CosmosResourceExistsError:
            pass  # another replica created it first; the patch below still applies
        container.patch_item(segment, partition_key=segment, patch_operations=operation)

    def claim(self, event: dict[str, Any]) -> bool:
        """Append an event unless its id is already stored: True when this call wrote
        it, False when it was there. The create is atomic, so two concurrent retries
        cannot both claim the same id. Raises when the store is down."""
        try:
            self._container("events").create_item(event)
        except CosmosResourceExistsError:
            return False
        return True

    def record_event(self, event: dict[str, Any]) -> bool:
        """Append an event, fail-open: a replay is accepted without a second copy, and
        False means it could not be persisted."""
        try:
            self.claim(event)
        except Exception:  # the caller decides what a lost event means
            log.exception("event %s not persisted", event.get("id"))
            return False
        return True

    def event(self, event_id: str) -> dict[str, Any] | None:
        """The stored event with this id, or None. Raises when the store is down."""
        try:
            return self._container("events").read_item(event_id, partition_key=event_id)
        except CosmosResourceNotFoundError:
            return None

    def delete_event(self, event_id: str) -> None:
        self._container("events").delete_item(event_id, partition_key=event_id)

    def events(self) -> list[dict[str, Any]]:
        """Every stored impression and reward: a cross-partition scan, for the offline
        rebuild only, never on the request path."""
        container = self._container("events")
        return list(
            container.query_items("SELECT * FROM c", enable_cross_partition_query=True)
        )

    def put_posterior(
        self, segment: str, alpha: list[float], beta: list[float]
    ) -> None:
        """Replace a product's posterior with one rebuilt offline."""
        self._container("posteriors").upsert_item(
            {"id": segment, "alpha": alpha, "beta": beta}
        )
