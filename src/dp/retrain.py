"""One pipeline run: simulate the policies, track them in MLflow, register the best.

    uv run python -m dp.retrain

One parent run per execution and one child per policy. The parent carries the
SHA-256 of the feature table and of the demand curves, so a registered policy traces
back to the exact data it saw. Only the best deployable policy is registered (the
oracle needs the ground truth, so it never is), as a new immutable version whose
artifact is the catalogue the API serves from.

Tracking goes wherever `MLFLOW_TRACKING_URI` points: a local SQLite file by default,
the free DagsHub server for the shared record.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

import mlflow

from dp.data import ORDERS_PARQUET
from dp.demand import CURVES_PARQUET
from dp.simulate import (
    BASE_CONVERSION,
    COST_SHARE,
    LOG_JSONL,
    load_world,
    play,
    write_catalogue,
    write_log,
)
from dp.thompson import CATALOGUE_PATH

EXPERIMENT = "dynamic-pricing"
MODEL_NAME = "dynamic-pricing-policy"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(
    curves: Path = CURVES_PARQUET,
    orders: Path = ORDERS_PARQUET,
    catalogue: Path = CATALOGUE_PATH,
    log: Path = LOG_JSONL,
    top: int = 50,
    requests: int = 20_000,
    log_requests: int = 2_000,
    seed: int = 0,
) -> str:
    """Returns the registered model version."""
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "sqlite:///mlflow.db"))
    world = load_world(curves, top)
    outcomes = play(world, requests, seed)
    write_catalogue(catalogue, world)
    write_log(log, world, log_requests, seed)

    mlflow.set_experiment(EXPERIMENT)
    with mlflow.start_run(run_name="retrain"):
        mlflow.log_params(
            {
                "products": len(world.codes),
                "arms": world.arms.shape[1],
                "requests_per_product": requests,
                "cost_share": COST_SHARE,
                "base_conversion": BASE_CONVERSION,
                "seed": seed,
                "features_sha256": sha256(orders),
                "curves_sha256": sha256(curves),
            }
        )
        mlflow.log_artifact(str(curves), "demand")
        mlflow.log_artifact(str(log), "log")

        child_ids: dict[str, str] = {}
        for name, outcome in outcomes.items():
            with mlflow.start_run(run_name=name, nested=True) as child:
                metrics = {
                    "margin": outcome.margin,
                    "expected_margin": outcome.expected,
                    "regret": outcome.regret,
                    "share_of_oracle": outcome.share_of_oracle,
                }
                if outcome.settled_at is not None:
                    settled = outcome.settled_at[outcome.settled_at < requests]
                    metrics["products_settled"] = len(settled)
                    if len(settled):
                        metrics["median_requests_to_settle"] = float(
                            sorted(settled)[len(settled) // 2]
                        )
                mlflow.log_metrics(metrics)
                child_ids[name] = child.info.run_id

        best = max(
            (o for o in outcomes.values() if o.policy != "oracle"),
            key=lambda o: o.expected,
        )
        mlflow.log_params({"best_policy": best.policy})
        mlflow.log_metric("best_share_of_oracle", best.share_of_oracle)

    with mlflow.start_run(run_id=child_ids[best.policy]):
        with tempfile.TemporaryDirectory() as tmp:
            policy = Path(tmp) / "policy.json"
            policy.write_text(json.dumps({"policy": best.policy}) + "\n")
            mlflow.log_artifact(str(policy), "policy")
        mlflow.log_artifact(str(catalogue), "policy")
        source = mlflow.get_artifact_uri("policy")

    client = mlflow.MlflowClient()
    if not client.search_registered_models(f"name = '{MODEL_NAME}'"):
        client.create_registered_model(MODEL_NAME)
    # ponytail: bare artifacts registered with create_model_version, because MLflow 3's
    # register_model only accepts a logged model. Wrap the policy as a pyfunc model if
    # the registry ever has to serve it.
    version = client.create_model_version(
        MODEL_NAME, source=source, run_id=child_ids[best.policy]
    )
    return str(version.version)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--top", type=int, default=50)
    parser.add_argument("--requests", type=int, default=20_000)
    args = parser.parse_args(argv)
    version = run(top=args.top, requests=args.requests)
    print(f"registered {MODEL_NAME} version {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
