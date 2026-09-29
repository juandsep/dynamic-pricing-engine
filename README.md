# Dynamic Pricing Engine

> Real-time price assignment with **Thompson Sampling** to maximize **LTV**, served from a **feature store** (Redis + Cosmos DB), tracked in **MLflow**, retrained on a schedule and deployed on **Azure**.

---

## The problem

A single price for the whole catalogue leaves money on the table:

- Customers with a high willingness to pay are charged **below** what they would accept.
- Price-sensitive customers are charged **above** and are lost.
- The optimal price **moves over time** — seasonality, stock, competition, live client signals — and a static model cannot follow it.

## The approach

A service that assigns a price **per customer in real time**, treating each price level as an *arm* of a multi-armed bandit problem and solving it with **Thompson Sampling**:

1. Sample from the Beta posterior of each price *arm* for the customer's segment.
2. Pick the arm with the highest expected value, respecting the price floor and ceiling.
3. Observe the outcome (conversion, margin, LTV) and **update the posterior**.
4. Explore naturally: uncertain arms keep receiving traffic instead of being switched off early.

The result is a policy that **learns on its own**, converges to the per-segment optimum and follows drift without manual retraining.

## Architecture

```
                        ┌───────────────────────────┐
   client ────▶  GET /price ──▶  ThompsonSampler     │
                        │              │             │
                        │              ▼             │
                        │      FeatureStore           │
                        │        ├─ Azure Cache for Redis   (online, <10 ms)
                        │        └─ Cosmos DB               (persistence / events)
                        │              │
                        │              ▼
                        └──────▶ MLflow (runs, metrics, registry)
                                       ▲
                                       │
                     GitHub Actions (weekly cron) ──▶ scripts/retrain.py
```

## Stack

| Layer | Technology |
|---|---|
| API | FastAPI + Uvicorn |
| Algorithm | Thompson Sampling (Beta posterior) on NumPy/SciPy |
| Feature store | Azure Cache for Redis (online) · Azure Cosmos DB (offline / events) |
| Tracking & registry | MLflow |
| Retraining | GitHub Actions (cron) |
| Deployment | Azure Container Apps + Azure Container Registry |
| Secrets | Azure Key Vault (OIDC federated auth in CI) |
| Observability | Application Insights + Log Analytics |
| Environment | **uv** (`pyproject.toml` + `uv.lock`) |
| Tests & lint | pytest · ruff |

## Project status

Roadmap in [`PLAN.md`](./PLAN.md).

- [x] **F0** · Foundations: repo, uv project, lockfile, tests, base CI
- [ ] **F1** · Feature store: Redis online + Cosmos DB, feature contracts and versioning
- [ ] **F2** · Algorithm: Beta posterior per arm/segment, price guards, reward = margin/LTV
- [ ] **F3** · API: `GET /price`, `POST /reward`, `/health`
- [ ] **F4** · MLflow tracking: parameters, metrics (LTV, conversion, regret), registry
- [ ] **F5** · Automated retraining (GitHub Actions, weekly cron)
- [ ] **F6** · Azure deployment (Container Apps, ACR, Key Vault)
- [ ] **F7** · Observability: LTV per arm, drift, latency, regret dashboards

## Repository layout

```
dynamic-pricing-engine/
├─ src/dp/
│   ├─ __init__.py     # package entry point
│   ├─ api.py          # FastAPI app: /price, /health
│   ├─ thompson.py     # Thompson Sampling policy
│   └─ store.py        # feature store: Redis (online) / Cosmos DB (persistence)
├─ tests/
│   ├─ unit/           # fast, no external services
│   └─ integration/    # wired against fakes or containers
├─ scripts/            # retrain.py, bootstrap, migrations
├─ docker/             # multi-stage Dockerfile
├─ docs/               # architecture notes
├─ infra/              # Terraform (azurerm)
├─ monitoring/         # dashboards and alerts
├─ .github/workflows/  # CI (and scheduled retraining)
├─ PLAN.md
└─ pyproject.toml      # dependencies managed with uv
```

## Quickstart

```bash
git clone https://github.com/juandsep/dynamic-pricing-engine.git
cd dynamic-pricing-engine

uv sync                  # create .venv from uv.lock
uv run pytest -q         # unit tests
uv run uvicorn dp.api:app --reload   # http://localhost:8000
```

Ask for a price:

```bash
curl "http://localhost:8000/price?user_id=user-42"
```

## Configuration

| Variable | Description |
|---|---|
| `REDIS_URL` | Azure Cache for Redis (online feature store) |
| `COSMOS_ENDPOINT` / `COSMOS_DATABASE` | Cosmos DB (events and attributes) |
| `MLFLOW_TRACKING_URI` | tracking / registry backend |
| `PRICE_MIN` / `PRICE_MAX` | allowed price range |
| `AZURE_KEYVAULT_URL` | secret source at runtime |

## Deployment

`docker build -f docker/Dockerfile -t dynamic-pricing-engine .` → push to **Azure Container Registry** → `az containerapp update`.
Terraform and notes in [`infra/`](./infra/README.md); pipeline in `.github/workflows/`.

## Success metrics

- Incremental LTV against a fixed-price baseline above the agreed threshold.
- p95 latency of `/price` below 50 ms.
- Zero violations of `PRICE_MIN` / `PRICE_MAX`.

## Related

Structure, CI and conventions follow the reference pipeline `uplift-modeling-pipeline`.

---

**Stack:** Python 3.11 · uv · FastAPI · NumPy/SciPy · Redis · Azure Cosmos DB · MLflow · Azure Container Apps · GitHub Actions
