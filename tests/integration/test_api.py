"""Integration tests for the pricing API (no external services required)."""

import json

import pytest
from fastapi.testclient import TestClient

from dp import api
from dp.api import app, get_sampler
from dp.thompson import CATALOGUE_PATH


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "catalogue.json"
    path.write_text(json.dumps({"A": {"arms": [1.0, 2.0, 3.0], "cost": 0.5}}))
    monkeypatch.setenv("CATALOGUE_PATH", str(path))
    monkeypatch.delenv("COSMOS_ENDPOINT", raising=False)
    get_sampler.cache_clear()
    yield TestClient(app)
    get_sampler.cache_clear()


def serve(client):
    response = client.get("/price", params={"user_id": "user-42", "product": "A"})
    assert response.status_code == 200
    return response.json()


def posterior():
    return get_sampler().store.posterior("A", 3)


def reward(client, impression_id, reward_id="r-1", converted=True, margin=1.5):
    return client.post(
        "/reward",
        json={
            "id": reward_id,
            "impression_id": impression_id,
            "converted": converted,
            "margin": margin,
        },
    )


def test_health_and_ready(client):
    assert client.get("/health").json() == {"status": "ok"}
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json() == {
        "status": "ready",
        "policy_version": "v1-thompson",
        "products": 1,
    }


def test_not_ready_without_a_catalogue(client, monkeypatch, tmp_path):
    monkeypatch.setenv("CATALOGUE_PATH", str(tmp_path / "missing.json"))
    get_sampler.cache_clear()
    assert client.get("/ready").status_code == 503


def test_the_shipped_catalogue_is_ready(monkeypatch):
    monkeypatch.delenv("CATALOGUE_PATH", raising=False)
    get_sampler.cache_clear()
    assert CATALOGUE_PATH.exists()
    assert TestClient(app).get("/ready").json()["products"] == 50
    get_sampler.cache_clear()


def test_price_is_an_arm_and_the_impression_is_logged(client):
    payload = serve(client)
    assert payload["price"] in (1.0, 2.0, 3.0)
    assert payload["policy_version"] == "v1-thompson"

    impression = get_sampler().store.event(payload["impression_id"])
    assert impression["segment"] == "A"
    assert impression["arm"] == payload["price"]
    assert 0 < impression["propensity"] <= 1


def test_a_duplicated_reward_moves_the_posterior_once(client):
    """The F4 check."""
    served = serve(client)
    arm = [1.0, 2.0, 3.0].index(served["price"])

    first = reward(client, served["impression_id"])
    assert first.json() == {"id": "r-1", "duplicate": False, "applied": True}
    after_first = posterior()
    assert after_first[0][arm] == 2.0

    again = reward(client, served["impression_id"])
    assert again.status_code == 200
    assert again.json()["duplicate"] is True
    assert posterior() == after_first


def test_a_reward_for_an_impression_never_served_is_404(client):
    response = reward(client, "i-never-served")
    assert response.status_code == 404
    assert posterior() == ([1.0] * 3, [1.0] * 3)


def test_a_late_reward_is_stored_but_not_applied(client, monkeypatch):
    served = serve(client)
    later = api._now()
    from datetime import timedelta

    monkeypatch.setattr(api, "_now", lambda: later + timedelta(hours=25))
    response = reward(client, served["impression_id"])
    assert response.json() == {"id": "r-1", "duplicate": False, "applied": False}
    assert get_sampler().store.event("r-1")["type"] == "reward"
    assert posterior() == ([1.0] * 3, [1.0] * 3)


def test_a_failed_posterior_update_is_503_and_the_retry_applies_it(client, monkeypatch):
    served = serve(client)
    store = get_sampler().store
    real = store.add_outcome

    def down(*args, **kwargs):
        raise ConnectionError("cosmos unreachable")

    monkeypatch.setattr(store, "add_outcome", down)
    assert reward(client, served["impression_id"]).status_code == 503
    assert store.event("r-1") is None  # rolled back, so the retry is not a duplicate

    monkeypatch.setattr(store, "add_outcome", real)
    assert reward(client, served["impression_id"]).json()["applied"] is True


def test_an_unreachable_store_is_503(client, monkeypatch):
    store = get_sampler().store

    def down(*args, **kwargs):
        raise ConnectionError("cosmos unreachable")

    monkeypatch.setattr(store, "event", down)
    assert reward(client, "i-1").status_code == 503


def test_unknown_product_is_404_and_inputs_are_validated(client):
    assert (
        client.get("/price", params={"user_id": "u", "product": "NOPE"}).status_code
        == 404
    )
    assert client.get("/price", params={"product": "A"}).status_code == 422
    assert reward(client, "i-1", margin=-1).status_code == 422
