"""A randomised price test recovers the elasticity it was generated with."""

import numpy as np
import pytest
from test_simulator import curves

from dp.experiment import estimate, main, requests_needed
from dp.simulate import attribute, build_world, load_events, write_log


def test_recovers_the_true_elasticity_with_honest_errors(tmp_path):
    # Low enough that no arm's conversion hits the simulator's cap at 1, which would
    # bend the curve the estimate is checked against.
    world = build_world(curves(), base_conversion=0.05)
    assert world.conversion.max() < 1
    path = tmp_path / "log.jsonl"
    write_log(path, world, requests=20_000, seed=11)
    rows, _ = attribute(*load_events(path))
    found = estimate(rows)
    for code, truth in zip(world.codes, curves()["elasticity"]):
        e = found[code]
        assert e["requests"] == 20_000
        assert abs(e["elasticity"] - truth) < 3 * e["se"], (code, e, truth)
        assert e["se"] < 0.2


def test_errors_shrink_with_the_square_root_of_the_sample():
    assert requests_needed(se=0.4, requests=2_000, target_se=0.2) == 8_000
    assert requests_needed(se=0.1, requests=2_000, target_se=0.2) == 500


def test_a_product_seen_at_one_price_has_no_slope():
    rows = [{"segment": "A", "arm": 2.0, "converted": i % 2 == 0} for i in range(100)]
    assert estimate(rows) == {}


def test_cli_prints_the_size_of_the_test(tmp_path, capsys):
    world = build_world(curves(), base_conversion=0.2)
    path = tmp_path / "log.jsonl"
    write_log(path, world, requests=2_000, seed=3)
    assert main(["--events", str(path), "--observational", str(tmp_path / "none")]) == 0
    out = capsys.readouterr().out
    assert "ELASTIC" in out and '"products": 2' in out
    assert "warning" not in out  # the uniform log is randomised


@pytest.mark.parametrize("seed", range(3))
def test_estimates_are_not_biased_toward_zero(tmp_path, seed):
    world = build_world(curves(), base_conversion=0.05)  # few sales on the dear arms
    path = tmp_path / "log.jsonl"
    write_log(path, world, requests=5_000, seed=seed)
    e = estimate(attribute(*load_events(path))[0])["ELASTIC"]
    assert abs(e["elasticity"] - (-3.0)) < 3 * e["se"]
    assert np.isfinite(e["se"])
