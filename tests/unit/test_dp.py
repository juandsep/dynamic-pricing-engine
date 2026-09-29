"""Unit tests for the pricing policy and the feature store."""

import pytest

from dp.store import DEFAULT_FEATURES, FeatureStore
from dp.thompson import ThompsonSampler


def test_sample_stays_inside_the_configured_range():
    sampler = ThompsonSampler((10, 20))
    for _ in range(50):
        assert 10 <= sampler.sample("user-1") <= 20


def test_sample_accepts_a_feature_vector():
    sampler = ThompsonSampler((10, 20))
    assert 10 <= sampler.sample("user-1", features={"segment": "high"}) <= 20


def test_inverted_range_is_rejected():
    with pytest.raises(ValueError):
        ThompsonSampler((100, 10))


def test_store_falls_back_to_defaults_without_redis():
    store = FeatureStore(redis_url="")
    features = store.get_features("user-1")
    assert features["user_id"] == "user-1"
    assert features["feature1"] == DEFAULT_FEATURES["feature1"]


def test_set_features_is_a_noop_without_redis():
    store = FeatureStore(redis_url="")
    store.set_features("user-1", {"feature1": 0.9})
