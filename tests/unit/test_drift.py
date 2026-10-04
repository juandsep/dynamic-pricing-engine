"""PSI stays quiet on the traffic the policy was registered on and fires on a shift."""

import json

import numpy as np
from test_simulator import curves

from dp.drift import DRIFT, main, profile, profile_from_pulls, psi, report
from dp.simulate import build_world, load_events, write_log


def impressions(tmp_path, world, requests=2_000, name="log.jsonl"):
    path = tmp_path / name
    write_log(path, world, requests, seed=1)
    return path, load_events(path)[0]


def test_identical_traffic_has_zero_psi():
    shares = {"a": 0.5, "b": 0.5}
    assert psi(shares, shares) == 0.0


def test_the_logged_traffic_matches_its_own_reference(tmp_path):
    world = build_world(curves())
    _, rows = impressions(tmp_path, world)
    # A uniform logging policy over two products and five arms.
    reference = profile_from_pulls(world.codes, np.ones((2, 5)))
    assert all(value < 0.01 for value in report(reference, profile(rows)).values())


def test_a_shift_in_the_mix_or_the_served_arms_is_drift(tmp_path):
    world = build_world(curves())
    _, rows = impressions(tmp_path, world)
    # Registered on a policy that served the cheapest arm, mostly for ELASTIC.
    pulls = np.array([[900, 0, 0, 0, 0], [100, 0, 0, 0, 0]])
    psis = report(profile_from_pulls(world.codes, pulls), profile(rows))
    assert psis["products"] > DRIFT
    assert psis["arms"] > DRIFT


def test_cli_reads_a_registered_reference_and_a_log(tmp_path, capsys):
    world = build_world(curves())
    log, _ = impressions(tmp_path, world)
    reference = tmp_path / "reference_profile.json"
    reference.write_text(json.dumps(profile_from_pulls(world.codes, np.ones((2, 5)))))
    assert main([str(reference), str(log)]) == 0
    out = capsys.readouterr().out
    assert "products  PSI 0.000  ok" in out
