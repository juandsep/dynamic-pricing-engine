"""Tests for the offline replay in dp.simulate."""

import json

import pytest

from dp.simulate import attribute, by_arm, load_events, snips


def _log(tmp_path, rows):
    path = tmp_path / "events.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def _impression(**overrides):
    row = {
        "type": "impression",
        "id": "i-1",
        "ts": "2026-09-01T10:00:00Z",
        "user_id": "u-1",
        "segment": "default",
        "arm": 25,
        "propensity": 0.5,
    }
    row.update(overrides)
    return row


def _reward(**overrides):
    row = {
        "type": "reward",
        "id": "r-1",
        "ts": "2026-09-01T11:00:00Z",
        "impression_id": "i-1",
        "converted": True,
        "margin": 10.0,
        "window_hours": 24,
    }
    row.update(overrides)
    return row


def test_impression_without_reward_is_censored_to_zero(tmp_path):
    impressions, rewards = load_events(_log(tmp_path, [_impression()]))
    rows, defects = attribute(impressions, rewards)
    assert defects == 0
    assert rows == [
        {
            "arm": 25,
            "arm_index": None,
            "segment": "default",
            "propensity": 0.5,
            "converted": False,
            "margin": 0.0,
        }
    ]


def test_second_reward_for_the_same_impression_is_a_defect_not_a_second_data_point(
    tmp_path,
):
    rows = [
        _impression(),
        _reward(),
        _reward(id="r-2", margin=99.0),
    ]
    impressions, rewards = load_events(_log(tmp_path, rows))
    joined, defects = attribute(impressions, rewards)
    assert defects == 1
    assert joined[0]["margin"] == 10.0


def test_per_arm_conversion_rate(tmp_path):
    rows = [
        _impression(id="i-1", arm=25),
        _reward(impression_id="i-1"),
        _impression(id="i-2", arm=25),
        _impression(id="i-3", arm=40),
    ]
    impressions, rewards = load_events(_log(tmp_path, rows))
    joined, _ = attribute(impressions, rewards)
    table = by_arm(joined)
    assert table[25]["served"] == 2
    assert table[25]["rate"] == 0.5
    assert table[40]["rate"] == 0.0


def test_snips_prefers_the_arm_that_earned(tmp_path):
    rows = [
        _impression(id="i-1", arm=25),
        _reward(impression_id="i-1", margin=10.0),
        _impression(id="i-2", arm=40),
    ]
    impressions, rewards = load_events(_log(tmp_path, rows))
    joined, _ = attribute(impressions, rewards)
    assert snips(joined, 25) == pytest.approx(10.0)
    assert snips(joined, 40) == 0.0
    assert snips(joined, 99) is None


def test_malformed_log_is_rejected(tmp_path):
    path = _log(tmp_path, [_impression()])
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"type": "click", "id": "x"}\n')
    with pytest.raises(ValueError, match="unknown type"):
        load_events(path)


@pytest.mark.parametrize("propensity", [0, 1.5, -0.1])
def test_propensity_must_be_a_probability(tmp_path, propensity):
    path = _log(tmp_path, [_impression(propensity=propensity)])
    with pytest.raises(ValueError, match="propensity"):
        load_events(path)
