"""The price test end to end, offline: shoppers with a hidden curve, the API in
experiment mode, the exported log, and an estimate that finds the hidden curve."""

import json

import pytest
from fastapi.testclient import TestClient

from dp import api
from dp import export as export_module
from dp.api import app, get_sampler
from dp.experiment import estimate
from dp.shoppers import buy_probability, run
from dp.simulate import attribute, load_events
from dp.thompson import EXPERIMENT_VERSION, in_experiment

KEY = "test-key"
ARMS = [1.0, 1.5, 2.0, 2.5, 3.0]


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "catalogue.json"
    path.write_text(json.dumps({"A": {"arms": ARMS, "cost": 0.5}}))
    monkeypatch.setenv("CATALOGUE_PATH", str(path))
    monkeypatch.delenv("COSMOS_ENDPOINT", raising=False)
    monkeypatch.setattr(api, "API_KEY", KEY)
    monkeypatch.setattr(api, "_bucket", api.TokenBucket(0))
    monkeypatch.setattr(api, "RATE_LIMIT_RPS", 0)
    monkeypatch.setattr(api, "EXPERIMENT_SHARE", 1.0)
    get_sampler.cache_clear()
    yield TestClient(app, headers={"X-API-Key": KEY})
    get_sampler.cache_clear()


def test_a_randomised_price_is_logged_with_its_propensity_and_sticks(client):
    first = client.get("/price", params={"user_id": "u1", "product": "A"}).json()
    again = client.get("/price", params={"user_id": "u1", "product": "A"}).json()
    assert first["policy_version"] == EXPERIMENT_VERSION
    assert first["price"] == again["price"]  # the same customer sees the same price
    impression = get_sampler().store.event(first["impression_id"])
    assert impression["propensity"] == pytest.approx(1 / len(ARMS))
    seen = {
        client.get("/price", params={"user_id": f"u{i}", "product": "A"}).json()[
            "price"
        ]
        for i in range(200)
    }
    assert seen == set(ARMS)


def test_the_experiment_share_splits_traffic():
    share = sum(in_experiment(f"u{i}", "A", 0.1) for i in range(20_000)) / 20_000
    assert share == pytest.approx(0.1, abs=0.01)
    assert not any(in_experiment(f"u{i}", "A", 0.0) for i in range(1_000))


def test_the_test_recovers_the_hidden_curve_not_the_observational_one(
    client, tmp_path, monkeypatch
):
    truth = {
        "A": {
            "elasticity": -1.2,
            "observational": -2.0,
            "median_price": 2.0,
            "base_conversion": 0.2,
        }
    }

    def send(method, path, body):
        response = client.request(method, path, json=body)
        return response.status_code, response.json()

    stats = run(send, truth, {"A": 0.5}, requests=4_000, rps=0, workers=1, seed=7)
    assert stats["failed"] == 0 and stats["served"] == 4_000
    assert stats["bought"] == pytest.approx(
        4_000 * sum(buy_probability(truth["A"], p) for p in ARMS) / len(ARMS), rel=0.1
    )

    monkeypatch.setattr(export_module, "Store", lambda: get_sampler().store)
    out = tmp_path / "events.jsonl"
    assert export_module.main([str(out)]) == 0
    e = estimate(attribute(*load_events(out))[0])["A"]
    assert abs(e["elasticity"] - (-1.2)) < 3 * e["se"]
    assert abs(e["elasticity"] - (-2.0)) > 3 * e["se"]  # not the observational slope
