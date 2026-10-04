# dynamic-pricing-engine

A single price for every customer leaves money on the table: buyers with a high
willingness to pay are charged less than they would accept, price-sensitive buyers
leave, and the price that maximises margin moves with stock, season and competition.
A static price cannot follow it.

This repository assigns a price per request, treating each price level as an arm of a
multi-armed bandit and solving it with Thompson Sampling: sample the Beta posterior of
every arm for the customer's segment, serve the highest, observe the outcome, update.
It is a portfolio project to practice the full MLOps loop on a zero budget — data
ingestion, demand modelling, offline policy evaluation, experiment tracking, a model
registry, a serving API, CI/CD and infrastructure as code on Azure.

- **Data:** UCI Online Retail II, about 1M order lines with the price actually charged
  and the quantity bought, fitted into a price–response model that acts as the
  simulator's ground truth.
- **Model:** Thompson Sampling, one Beta posterior per price arm and segment, against a
  fixed-price baseline, compared by regret and cumulative margin.
- **Stack:** DuckDB, MLflow, FastAPI, Azure Container Apps, Cosmos DB, Terraform,
  GitHub Actions.
- **Status:** foundations and the data contract are in; the policy still draws
  uniformly, and the sections below describe the target end state
  ([PLAN.md](PLAN.md) is the roadmap).

[![CI](https://github.com/juandsep/dynamic-pricing-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/juandsep/dynamic-pricing-engine/actions/workflows/ci.yml)

## Results

Not measured yet: the policy serves a uniform draw, so any number here would be
fabricated. The comparison the project reports once it runs:

| Policy | Regret vs oracle | Cumulative margin | Share of oracle |
|---|---|---|---|
| Fixed price (baseline) | — | — | — |
| Uniform random | — | — | — |
| Thompson Sampling | — | — | — |

**Regret** is what the best fixed price in hindsight would have earned minus what the
policy earned — the pricing equivalent of a Qini curve. Offline, the same comparison
comes out of `python -m dp.simulate`, which replays a logged policy and estimates a
fixed-price baseline by propensity weighting (SNIPS). Both paths are reported, because
a simulator with known propensities and a real log with unknown ones are not the same
evidence.

## Architecture

| Component | What it does | Runs on |
|---|---|---|
| Ingestion | Raw order lines to Parquet, price–response fitted per segment | DuckDB, local or GitHub Actions |
| `dp.simulate` | Simulator on the fitted curves (oracle, modal, uniform, Thompson), uniform log with known propensities, replay with SNIPS | anywhere, numpy |
| Thompson policy | Beta posterior per price arm and segment, with price guards | the API process |
| Cosmos DB | The posterior document, served arms and rewards | Azure, provisioned 1000 RU/s on the free tier |
| MLflow | Experiment tracking and the policy registry | DagsHub, free hosted |
| dp-api | FastAPI, `GET /price` and `POST /reward` | Container Apps, scales to zero |
| GHCR | The API image, public package pulled anonymously | GitHub |
| GitHub Actions | CI on every pull request, deploy on `dev`, weekly retrain | GitHub |
| Terraform | Everything above the subscription-scope bootstrap | local, applied and destroyed around a demo |

Nothing bills while idle: every resource is free-tier, inside a per-subscription free
grant, or destroyed after use, and the budget is fixed at 10 USD/month as a tripwire.
The prices behind each rejected alternative — Redis, ACR, a self-hosted MLflow backend —
are in [infra/README.md](infra/README.md).

## Training pipeline

1. **ingest** — DuckDB reads the raw CSVs and writes Parquet, keeping the price actually
   charged on every order line.
2. **demand** — fits a price–response curve per segment on a held-out time split. This is
   the part that needs real data: without price variation in the log there is nothing to
   estimate.
3. **simulate** — generates a bandit log from the fitted demand with known propensities,
   so a policy can be evaluated honestly before it ever serves a request.
4. **compare** — runs the fixed price, a uniform random policy and Thompson Sampling over
   the same log, one MLflow run each, and reports regret.
5. **register** — registers the calibrated prior as a new immutable policy version;
   nothing is overwritten.
6. **replay** — `python -m dp.simulate` on the log, for the numbers in this README and for
   the check that a change to the policy still beats the baseline.

## Serving

`GET /price` returns a price for a customer and records the arm it served, so a later
`POST /reward` can attribute the outcome. The served price is always inside `PRICE_MIN` /
`PRICE_MAX`, and each response carries the policy version that produced it.

`POST /reward` is idempotent by request id: a retried reward cannot move the posterior
twice, and a reward for an arm that was never served is rejected. When the store cannot be
written the endpoint answers **503** instead of a silent 200, because a lost outcome
degrades learning while a false success corrupts it.

The serving path never reads the model registry — it reads the posterior from the store —
so the API needs no tracking credential. The request path, the failure behaviour and the
ceiling behind the single-replica design are in [docs/architecture.md](docs/architecture.md).

## Model tracking and retraining

Every pipeline run logs one parent MLflow run (dataset, policies compared, regret and
margin of each) and one child run per policy, with the demand model and the log attached.
Only the best policy is registered, and the feature table's SHA-256 is logged as a
parameter so a policy can be traced to the exact data it saw.

UCI Online Retail II does not change, so retraining it reproduces the same numbers. With
live traffic, retrain when a new randomised price test closes, when the margin measured on
that test drops, or when the traffic mix drifts — a segment that changes mid-log
invalidates the history behind the posterior.

## Data

The exercise runs on **UCI Online Retail II**: 1,067,371 order lines from a UK online
retailer between December 2009 and December 2011, across 5,305 products and 53,628 invoices,
with `Invoice`, `StockCode`, `Description`, `Quantity`, `InvoiceDate`, `Price`, `Customer ID`
and `Country`. It is free, needs no account and downloads over plain HTTP,
which matters because CI fetches it too.

What makes it usable for pricing: the same product is sold at several different prices
over time, so the price–response curve is identifiable, and quantity gives an outcome to
maximise. Measured on the download: after dropping returns, zero prices and cancellations,
**88.6% of products have at least two price points and 77.6% have three or more** (median 4),
and 99.2% of the rows sit behind those products. Fitting them (`python -m dp.demand`) keeps
2,759 products, with a median elasticity of −2.41 and a median R² of 0.53 — 0.26 when a curve
fitted before May 2011 is measured on the months after it. What it does **not** have is propensities — nobody logged the probability of the
price that was charged — so it cannot be used for off-policy evaluation directly. That is
why the pipeline fits demand on the real data and then simulates a log with known
propensities on top of it.

The event log the service writes is a separate contract, specified in
[docs/data-contract.md](docs/data-contract.md) with the attribution rules and the volume a
policy needs before its posteriors mean anything.

## Run locally

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pre-commit install
uv run pytest -q

scripts/fetch_data.sh                  # 44 MB into data/raw/ (git-ignored)
uv run python -m dp.data               # clean both sheets → data/processed/orders.parquet
uv run python -m dp.demand             # price-response curves → data/processed/

uv run uvicorn dp.api:app --reload     # http://localhost:8000

curl "http://localhost:8000/price?user_id=user-42"
```

Simulate the four policies on the fitted curves and write a uniform log, then replay it
(log format in `docs/data-contract.md`):

```bash
uv run python -m dp.simulate
uv run python -m dp.simulate --events data/processed/simulated_log.jsonl --baseline-price 2.95
```

## Reproduce on Azure

The one-off bootstrap — resource providers, the 10 USD budget, the GitHub Actions identity
with its federated credentials and the role assignment — is written out step by step in
[infra/README.md](infra/README.md). After that everything is Terraform, applied before a
demo and destroyed after.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `COSMOS_ENDPOINT` | none | Cosmos DB account; unset runs on defaults with no credentials required |
| `COSMOS_DATABASE` | `pricing` | Database name |
| `MLFLOW_TRACKING_URI` | `sqlite:///mlflow.db` | Tracking and registry backend |
| `PRICE_MIN` / `PRICE_MAX` | `10` / `100` | Allowed price range |
| `POLICY_VERSION` | none | Policy version to serve, never a floating alias |

No connection strings and no key vault: the service authenticates to Cosmos with its managed
identity, and CI authenticates to Azure with OIDC federated credentials.

## Project layout

```
src/dp/
  api.py           FastAPI app: /price, /reward, /health
  thompson.py      Thompson Sampling policy
  store.py         posterior and event store
  simulate.py      policy simulator, logged-bandit generator, offline replay
scripts/           dataset download, retraining
docs/              architecture and data contract
infra/             Terraform and the one-off bootstrap
monitoring/        dashboards and drift checks
tests/             unit and integration tests
```

## Contributing

Changes go on a `feat/`, `fix/` or `chore/` branch cut from `dev` and merge into `dev`
through a pull request; `main` only receives pull requests from `dev`. Details and checks
are in [CONTRIBUTING.md](CONTRIBUTING.md).

---

**Stack:** Python 3.11 · uv · FastAPI · NumPy/SciPy · DuckDB · Azure Cosmos DB · MLflow · Azure Container Apps · GHCR · GitHub Actions
