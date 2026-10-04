"""Integration tests for the pricing API (no external services required)."""

import json

import pytest
from fastapi.testclient import TestClient

from dp.api import app, get_sampler


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "catalogue.json"
    path.write_text(json.dumps({"A": {"arms": [1.0, 2.0, 3.0], "cost": 0.5}}))
    monkeypatch.setenv("CATALOGUE_PATH", str(path))
    monkeypatch.delenv("COSMOS_ENDPOINT", raising=False)
    get_sampler.cache_clear()
    yield TestClient(app)
    get_sampler.cache_clear()


def test_health_reports_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_price_is_an_arm_and_the_impression_is_logged(client):
    response = client.get("/price", params={"user_id": "user-42", "product": "A"})
    assert response.status_code == 200

    payload = response.json()
    assert payload["user_id"] == "user-42"
    assert payload["price"] in (1.0, 2.0, 3.0)
    assert payload["policy_version"] == "v1-thompson"

    events = get_sampler().store._container("events").items
    impression = events[payload["impression_id"]]
    assert impression["segment"] == "A"
    assert impression["arm"] == payload["price"]
    assert 0 < impression["propensity"] <= 1


def test_unknown_product_is_404(client):
    response = client.get("/price", params={"user_id": "u", "product": "NOPE"})
    assert response.status_code == 404


def test_price_requires_a_user_id_and_a_product(client):
    assert client.get("/price", params={"product": "A"}).status_code == 422
    assert client.get("/price", params={"user_id": "u"}).status_code == 422
