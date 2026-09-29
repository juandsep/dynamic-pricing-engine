"""Scheduled retraining of the pricing policy.

Run by the weekly GitHub Actions workflow. It replays the events stored in
Cosmos DB, recalibrates the Thompson Sampling priors and registers the
resulting policy in MLflow.

Placeholder: implement event loading and the posterior update.
"""

from __future__ import annotations


def main() -> None:
    """Replay events, recalibrate priors and register the policy."""
    # TODO: read events from Cosmos DB -> recompute Beta posteriors per arm/segment
    # TODO: mlflow.log_params / log_metrics, then register the candidate policy
    print("retrain: noop (placeholder)")


if __name__ == "__main__":
    main()
