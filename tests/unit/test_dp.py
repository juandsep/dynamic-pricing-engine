"""The F3 check: rewards move the posterior, and a restart preserves it."""

import numpy as np
import pytest

from dp.store import MemoryContainer, Store
from dp.thompson import ThompsonSampler

CATALOGUE = {"A": {"arms": [1.0, 2.0, 3.0], "cost": 0.5}}


def containers():
    return {"posteriors": MemoryContainer(), "events": MemoryContainer()}


def sampler(backend, seed=0):
    return ThompsonSampler(
        CATALOGUE, Store(containers=backend), np.random.default_rng(seed)
    )


def test_two_rewards_move_the_posterior_and_a_restart_keeps_them():
    backend = containers()
    first = sampler(backend)
    first.reward("A", 1, converted=True)
    first.reward("A", 1, converted=False)

    restarted = sampler(backend)  # new process, same Cosmos containers
    assert restarted.store.posterior("A", 3) == ([1.0, 2.0, 1.0], [1.0, 2.0, 1.0])


def test_a_product_never_rewarded_serves_the_uniform_prior():
    assert Store(containers=containers()).posterior("A", 3) == ([1.0] * 3, [1.0] * 3)


def test_the_posterior_steers_the_quote():
    backend = containers()
    policy = sampler(backend)
    for _ in range(200):
        policy.reward("A", 2, converted=True)
        policy.reward("A", 0, converted=False)
        policy.reward("A", 1, converted=False)
    quote = policy.quote("A")
    assert (quote.arm, quote.price) == (2, 3.0)
    assert quote.propensity > 0.99


def test_quote_carries_a_propensity_and_stays_inside_the_guard():
    policy = ThompsonSampler(
        CATALOGUE, Store(containers=containers()), price_range=(1.5, 2.5)
    )
    for _ in range(50):
        quote = policy.quote("A")
        assert 1.5 <= quote.price <= 2.5
        assert 0 < quote.propensity <= 1


def test_unknown_arm_and_inverted_guard_are_rejected():
    with pytest.raises(ValueError):
        sampler(containers()).reward("A", 3, converted=True)
    with pytest.raises(ValueError):
        ThompsonSampler(CATALOGUE, Store(containers=containers()), price_range=(3, 1))


def test_store_without_endpoint_needs_no_credentials():
    store = Store(endpoint="")
    store.add_outcome("A", 0, True, 3)
    assert store.posterior("A", 3)[0] == [2.0, 1.0, 1.0]


def test_an_unreachable_store_serves_the_prior_and_reports_lost_events():
    class Down:
        def __getattr__(self, name):
            def fail(*args, **kwargs):
                raise ConnectionError("cosmos unreachable")

            return fail

    store = Store(containers={"posteriors": Down(), "events": Down()})
    assert store.posterior("A", 3) == ([1.0] * 3, [1.0] * 3)
    assert store.record_event({"id": "i-1"}) is False
    with pytest.raises(ConnectionError):
        store.add_outcome("A", 0, True, 3)


def test_a_replayed_event_is_stored_once():
    store = Store(containers=containers())
    assert store.record_event({"id": "i-1", "type": "impression"})
    assert store.record_event({"id": "i-1", "type": "impression"})
    assert len(store._container("events").items) == 1
