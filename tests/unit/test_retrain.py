"""A pipeline run leaves one parent run, one child per policy, and one new version."""

import json
from pathlib import Path

import mlflow
import pandas as pd
from test_simulator import curves

from dp.retrain import EXPERIMENT, MODEL_NAME, run, sha256


def test_run_tracks_every_policy_and_registers_the_best(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MLFLOW_TRACKING_URI", f"sqlite:///{tmp_path / 'mlflow.db'}")
    curves_path = tmp_path / "curves.parquet"
    curves().to_parquet(curves_path)
    orders = tmp_path / "orders.parquet"
    pd.DataFrame({"x": [1]}).to_parquet(orders)
    catalogue = tmp_path / "catalogue.json"

    kwargs = {
        "curves": curves_path,
        "orders": orders,
        "catalogue": catalogue,
        "log": tmp_path / "log.jsonl",
        "requests": 2_000,
        "log_requests": 10,
    }
    assert run(**kwargs) == "1"
    assert run(**kwargs) == "2"  # a rerun is a new version, never an overwrite

    runs = mlflow.search_runs(experiment_names=[EXPERIMENT])
    parents = runs[runs["tags.mlflow.parentRunId"].isna()]
    children = runs[runs["tags.mlflow.parentRunId"].notna()]
    assert len(parents) == 2
    assert sorted(children["tags.mlflow.runName"]) == sorted(
        ["oracle", "modal", "uniform", "thompson"] * 2
    )
    assert set(parents["params.features_sha256"]) == {sha256(orders)}
    assert set(parents["params.best_policy"]) == {"thompson"}

    version = mlflow.MlflowClient().get_model_version(MODEL_NAME, "2")
    thompson = children[children["tags.mlflow.runName"] == "thompson"]
    assert version.run_id in set(thompson["run_id"])
    policy = mlflow.artifacts.download_artifacts(f"{version.source}/catalogue.json")
    assert json.loads(Path(policy).read_text()) == json.loads(catalogue.read_text())
