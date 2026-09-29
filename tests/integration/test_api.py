"""Integration tests for the pricing API (no external services required)."""

from fastapi.testclient import TestClient

from dp.api import app

client = TestClient(app)


def test_health_reports_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_price_is_returned_for_a_customer():
    response = client.get("/price", params={"user_id": "user-42"})
    assert response.status_code == 200

    payload = response.json()
    assert payload["user_id"] == "user-42"
    assert isinstance(payload["price"], int)
    assert 10 <= payload["price"] <= 100


def test_price_requires_a_user_id():
    assert client.get("/price").status_code == 422
