# Plan — Dynamic Pricing Engine

Goal: assign prices in real time with Thompson Sampling to maximize LTV, backed by a feature store, automated retraining and continuous deployment on Azure.

Each phase is one short-lived branch cut from `dev`, one pull request, one concern.

## Phases

- [x] **F0 · Foundations** — git repo, uv project, lockfile, pytest, base CI.
- [ ] **F1 · Feature store** — `store.py`: Redis online reads (p99 < 10 ms) plus Cosmos DB for events and durable attributes. Feature contracts and versioning.
- [ ] **F2 · Algorithm** — `thompson.py`: Beta posterior per price arm and per segment; reward = observed margin/LTV. Exploration policy plus price floor/ceiling guards.
- [ ] **F3 · API** — `api.py`: `GET /price`, `POST /reward` (conversion feedback), `/health`, feature batching.
- [ ] **F4 · Tracking** — MLflow: log parameters, metrics (LTV, conversion, regret) and register candidate policies.
- [ ] **F5 · Retraining** — scheduled GitHub Actions workflow (weekly cron) that recalibrates priors and registers them in MLflow.
- [ ] **F6 · Deployment** — Docker → Azure Container Registry → Container Apps; environment variables and secrets from Key Vault.
- [ ] **F7 · Observability** — dashboards (LTV per arm, feature drift, latency) and alerts.

## Success metrics

- Incremental LTV versus a fixed-price baseline above the agreed threshold.
- p95 latency of `/price` below 50 ms.
- Zero price floor/ceiling violations.

## Reference

Structure, CI and conventions follow `uplift-modeling-pipeline`.
