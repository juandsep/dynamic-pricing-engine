# Plan — Dynamic Pricing Engine

Goal: assign prices in real time with Thompson Sampling to maximize LTV, backed by a feature store, automated retraining and continuous deployment on Azure with no fixed monthly cost.

Each phase is one short-lived branch cut from `dev`, one pull request, one concern.

## Phases

- [x] **F0 · Foundations** — git repo, uv project, lockfile, pytest, base CI.
- [ ] **F0.5 · Data contract** — `docs/data-contract.md` and `src/dp/simulate.py`: the event schema, the attribution rules, and an offline replay that reports per-arm coverage and a propensity-weighted baseline estimate.
- [ ] **F1 · Feature store** — `store.py`: Cosmos DB for the posterior, the events and the durable attributes. Feature contracts and versioning.
- [ ] **F2 · Algorithm** — `thompson.py`: Beta posterior per price arm and per segment; reward = observed margin/LTV. Exploration policy plus price floor/ceiling guards.
- [ ] **F3 · API** — `api.py`: `GET /price`, `POST /reward` (conversion feedback, idempotent), `/health`, feature batching.
- [ ] **F4 · Tracking** — MLflow (hosted free on DagsHub): log parameters, metrics (LTV, conversion, regret) and register candidate policies.
- [ ] **F5 · Retraining** — scheduled GitHub Actions workflow (weekly cron) that recalibrates priors and registers them in MLflow.
- [ ] **F6 · Deployment** — Docker → GHCR → Container Apps; configuration through environment variables, authentication through a managed identity. No key vault, no registry credentials.
- [ ] **F7 · Observability** — dashboards (LTV per arm, feature drift, latency) and alerts.

## Success metrics

- Incremental LTV versus a fixed-price baseline above the agreed threshold.
- p95 latency of `/price` below 50 ms.
- Zero price floor/ceiling violations.
- Zero fixed monthly cost: every resource free-tier, inside a free grant, or destroyed while idle.

## Reference

Structure, CI and conventions follow `uplift-modeling-pipeline`.
