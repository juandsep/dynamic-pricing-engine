"""The posterior rebuilt from the log counts every outcome once, late ones included."""

import json

import numpy as np
import pytest
from test_simulator import curves

from dp import rebuild as rebuild_module
from dp.rebuild import main, rebuild
from dp.simulate import build_world, load_events, write_log
from dp.store import MemoryContainer, Store

CATALOGUE = {"A": {"arms": [1.0, 2.0, 3.0], "cost": 0.5}}


def impression(i, arm, segment="A"):
    return {
        "type": "impression",
        "id": f"i-{i}",
        "ts": "2026-10-01T00:00:00Z",
        "user_id": "u",
        "segment": segment,
        "arm": 1.0 + arm,
        "arm_index": arm,
        "propensity": 1 / 3,
    }


def reward(i, converted=True, late=False):
    return {
        "type": "reward",
        "id": f"r-{i}",
        "ts": "2026-10-03T00:00:00Z" if late else "2026-10-01T01:00:00Z",
        "impression_id": f"i-{i}",
        "converted": converted,
        "margin": 1.0 if converted else 0.0,
        "window_hours": 24,
    }


def test_counts_conversions_misses_and_late_rewards_once():
    impressions = [
        impression(1, 0),
        impression(2, 0),
        impression(3, 2),
        impression(4, 2),
    ]
    rewards = [reward(1), reward(1), reward(3, late=True), reward(4, converted=False)]
    posteriors, skipped = rebuild(impressions, rewards, CATALOGUE)
    # arm 0: one conversion, one impression with no reward (censored to a miss);
    # arm 2: a late conversion still counts, plus an explicit miss.
    assert posteriors["A"] == ([2.0, 1.0, 2.0], [2.0, 1.0, 2.0])
    assert skipped == 0


def test_impressions_outside_the_catalogue_are_counted_not_applied():
    impressions = [impression(1, 0, segment="GONE"), impression(2, 7)]
    posteriors, skipped = rebuild(impressions, [], CATALOGUE)
    assert skipped == 2
    assert posteriors["A"] == ([1.0] * 3, [1.0] * 3)


def test_rebuild_from_a_randomised_log_recovers_each_conversion_rate(tmp_path):
    world = build_world(curves(), base_conversion=0.3)
    path = tmp_path / "log.jsonl"
    write_log(path, world, requests=20_000, seed=5)
    catalogue = {
        c: {"arms": world.arms[i].tolist(), "cost": 0}
        for i, c in enumerate(world.codes)
    }
    posteriors, _ = rebuild(*load_events(path), catalogue)
    for i, code in enumerate(world.codes):
        alpha, beta = (np.array(v) for v in posteriors[code])
        assert alpha / (alpha + beta) == pytest.approx(world.conversion[i], abs=0.02)


def test_cli_reads_the_store_and_writes_back_only_with_write(
    tmp_path, monkeypatch, capsys
):
    containers = {"posteriors": MemoryContainer(), "events": MemoryContainer()}
    store = Store(containers=containers)
    for event in (impression(1, 1), reward(1)):
        store.claim(event)
    monkeypatch.setattr(rebuild_module, "Store", lambda: store)
    catalogue = tmp_path / "catalogue.json"
    catalogue.write_text(json.dumps(CATALOGUE))

    assert main(["--catalogue", str(catalogue)]) == 0
    assert containers["posteriors"].items == {}  # a dry run writes nothing
    assert main(["--catalogue", str(catalogue), "--write"]) == 0
    assert store.posterior("A", 3) == ([1.0, 2.0, 1.0], [1.0, 1.0, 1.0])
    assert "wrote 1 posteriors" in capsys.readouterr().out
