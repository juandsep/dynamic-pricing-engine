# Dynamic Pricing Engine

> Real-time price assignment with **Thompson Sampling** to maximize **LTV**, served from a **Cosmos DB** store, tracked in **MLflow**, retrained on a schedule and deployed on **Azure** with no fixed monthly cost.

[![CI](https://github.com/juandsep/dynamic-pricing-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/juandsep/dynamic-pricing-engine/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11-blue)
![License](https://img.shields.io/badge/license-MIT-green)

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
                        │        └─ Cosmos DB   (posterior + events)
                        │              │
                        │              ▼
                        └──────▶ MLflow (free hosted tracking + registry)
                                       ▲
                                       │
                     GitHub Actions (weekly cron) ──▶ scripts/retrain.py
```

The posterior and the durable events live in the **same Cosmos DB account**. The service keeps
exactly one replica, so a separate sub-millisecond cache (Redis, ~20 USD/month) would buy nothing
that a Cosmos point read does not already provide; it comes back only when replicas > 1.

## Stack

| Layer | Technology |
|---|---|
| API | FastAPI + Uvicorn |
| Algorithm | Thompson Sampling (Beta posterior) on NumPy/SciPy |
| Feature store | Azure Cosmos DB (posterior, durable events and attributes) |
| Tracking & registry | MLflow, hosted free on DagsHub |
| Retraining | GitHub Actions (cron) |
| Deployment | Azure Container Apps, image from GHCR |
| Secrets | none — managed identity to Cosmos, OIDC in CI |
| Observability | Container Apps logs (Log Analytics optional) |
| Environment | **uv** (`pyproject.toml` + `uv.lock`) |
| Tests & lint | pytest · ruff |

## Cost

Every Azure resource is either free-tier or inside a per-subscription free grant, so the running
bill is **0 USD/month** with no fixed line item:

| Resource | Cost | Basis |
|---|---|---|
| Container Apps (consumption, min 0 replicas) | 0 | first 180,000 vCPU-s, 360,000 GiB-s and 2M requests per subscription per month are free; a scaled-to-zero revision is not charged |
| Cosmos DB, provisioned 1000 RU/s | 0 | free tier: the first 1000 RU/s and 25 GB are free for the lifetime of the account, one per subscription, opted into at creation |
| GitHub Actions (CI + weekly retrain) | 0 | free on public repositories |
| GHCR image storage | 0 | free for public packages |
| DagsHub hosted MLflow | 0 | free per repository |
| Log Analytics | 0 | optional; the free ingestion grant covers a demo by orders of magnitude |

Rejected on cost, with the price that decided it (Azure retail prices API, September 2026): **Azure Cache for
Redis** at ~20 USD/month, **Azure Container Registry Basic** at ~5.03 USD/month (it bills even when
nothing is deployed), and **MLflow on Container Apps with a PostgreSQL backend** at ~15-20 USD/month.
Free-tier throughput is *not* available to Cosmos serverless accounts, so this project uses
provisioned throughput explicitly.

The binding ceilings, stated rather than hidden: 1000 RU/s is fixed throughput, so a spike beyond it
returns 429s (upgrade path: autoscale, then serverless); the free grants are per subscription and
shared with anything else in it; and everything here is created and destroyed around a demo
(`terraform apply` / `terraform destroy`) so that no resource bills while idle.

## Project status

Roadmap in [`PLAN.md`](./PLAN.md).

- [x] **F0** · Foundations: repo, uv project, lockfile, tests, base CI
- [x] **F0.5** · Data contract and offline log simulator
- [ ] **F1** · Feature store: Cosmos DB, feature contracts and versioning
- [ ] **F2** · Algorithm: Beta posterior per arm/segment, price guards, reward = margin/LTV
- [ ] **F3** · API: `GET /price`, `POST /reward`, `/health`
- [ ] **F4** · MLflow tracking: parameters, metrics (LTV, conversion, regret), registry
- [ ] **F5** · Automated retraining (GitHub Actions, weekly cron)
- [ ] **F6** · Azure deployment (Container Apps, GHCR)
- [ ] **F7** · Observability: LTV per arm, drift, latency, regret dashboards

## Repository layout

```
dynamic-pricing-engine/
├─ src/dp/
│   ├─ __init__.py     # package entry point
│   ├─ api.py          # FastAPI app: /price, /health
│   ├─ simulate.py     # offline replay of a logged policy
│   ├─ thompson.py     # Thompson Sampling policy
│   └─ store.py        # feature store: Cosmos DB (posterior + events)
├─ tests/
│   ├─ unit/           # fast, no external services
│   └─ integration/    # wired against fakes or containers
├─ scripts/            # retrain.py, bootstrap, migrations
├─ docker/             # multi-stage Dockerfile
├─ docs/               # architecture and data contract
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

Replay a logged policy offline (format in [`docs/data-contract.md`](./docs/data-contract.md)):

```bash
uv run python -m dp.simulate --events events.jsonl --baseline-price 25
```

## Configuration

| Variable | Description |
|---|---|
| `COSMOS_ENDPOINT` / `COSMOS_DATABASE` | Cosmos DB (posterior, events and attributes) |
| `MLFLOW_TRACKING_URI` | tracking / registry backend |
| `PRICE_MIN` / `PRICE_MAX` | allowed price range |

No connection strings and no key vault: the service authenticates to Cosmos with a managed identity,
and CI authenticates to Azure with OIDC.

## Deployment

`docker build -f docker/Dockerfile -t dynamic-pricing-engine .` → push to **GHCR** → the Container App
pulls the public package image with no registry credentials.
Terraform and notes in [`infra/`](./infra/README.md); pipeline in `.github/workflows/`.

## Success metrics

- Incremental LTV against a fixed-price baseline above the agreed threshold.
- p95 latency of `/price` below 50 ms.
- Zero violations of `PRICE_MIN` / `PRICE_MAX`.

## Related

Structure, CI and conventions follow the reference pipeline `uplift-modeling-pipeline`.

---

**Stack:** Python 3.11 · uv · FastAPI · NumPy/SciPy · Azure Cosmos DB · MLflow · Azure Container Apps · GHCR · GitHub Actions
