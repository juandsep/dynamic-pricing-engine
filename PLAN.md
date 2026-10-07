# Plan — Dynamic Pricing Engine

Goal: assign prices per request with Thompson Sampling to maximise margin, on real
price–response data, with offline policy evaluation, tracking, a registry, a serving API,
CI/CD and infrastructure as code on Azure at zero monthly cost.

Each phase below is one branch cut from `dev` and one pull request into `dev`
(`CONTRIBUTING.md`). A phase is done when its check passes, not when its files exist.

## Status

F9 landed: every phase is merged. Everything runs on a laptop; Azure only hosts the demo,
applied before it and destroyed after.

Staging was applied on 2026-10-05 and checked end to end: `/ready` with 50 products, a price,
a reward applied to the posterior in Cosmos through the managed identity (the atomic `incr`
on an array index, until then only exercised in memory), the same reward answered as a
duplicate, 401 without the key, and `deploy.yml` logging in by OIDC, rolling the app onto the
commit's image and passing its smoke test.
The evidence (verbatim live session, CLI inventory, screenshots) is in `docs/evidence/`, and
the stack was destroyed afterwards the same day. On 2026-10-07 it was applied again in
experiment mode for a randomised price test with 20,556 simulated shoppers: the hidden
elasticity was recovered for 9 of 10 products and the observational one rejected for all 10
(`docs/evidence/price-experiment.md`), and the stack destroyed again; `AZURE_CONTAINER_APP` was removed so pushes to
`dev` publish the image without deploying.

| | State |
|---|---|
| Foundations, data contract, offline replay | merged |
| **F1** ingest and demand model | merged, measured numbers under F1 |
| **F2** simulator with known propensities | merged, measured numbers under F2 |
| **F3** Thompson policy and Cosmos store | merged |
| **F4** MLflow tracking and the reward contract | merged |
| **F5** serving limits and payload contract | merged |
| **F6** Azure infrastructure | merged; planned against the subscription, not applied |
| **F7** CI/CD and retraining | merged; deploy job skipped until the bootstrap variables exist |
| **F8** drift and demo | merged; demo published on Hugging Face |
| **F9** documentation reconciliation | merged |

On `dev` today: `scripts/fetch_data.sh`, `src/dp/data.py` (DuckDB ingest of both sheets to
Parquet), `src/dp/demand.py` (per-product curves, measured out of sample), `src/dp/simulate.py`
(simulator on the curves, four policies, uniform log, catalogue, replay), `src/dp/thompson.py`
(Thompson Sampling per product), `src/dp/store.py` (posteriors and events in Cosmos DB, in
memory without an endpoint), `src/dp/retrain.py` (MLflow runs and registry), the served
catalogue `src/dp/catalogue.json`, FastAPI `GET /price`, `POST /reward` (API key, rate limit, size limit),
`/health`, `/ready` and `/metrics`, `docs/data-contract.md`, and 45 offline tests. The API
image carries serving dependencies only (383 MB); the pipeline is the `pipeline` group.

```bash
scripts/fetch_data.sh          # 44 MB → data/raw/, skipped when already there
uv run python -m dp.data       # 9s → data/processed/orders.parquet
uv run python -m dp.demand     # 3s → curves and data/processed/demand_summary.json
uv run python -m dp.simulate   # 2s → policy table, simulated_log.jsonl, catalogue.json
uv run python -m dp.retrain    # 4s → the same run tracked in MLflow, best policy registered
```

Azure: nothing here has been applied. `infra/` is a README and a bootstrap, there is no
Terraform state, and the `az` CLI is not installed on the development machine. The one piece
of the bootstrap that has been run is the 10 USD subscription budget, which only sends mail
(`infra/README.md`). `data/` is git-ignored and rebuilt by the commands above, so it does not
travel with the repo: the numbers in this file are how a fresh clone checks it reproduced the
same thing.

## Dataset

**Chosen: UCI Online Retail II** — 1,067,371 order lines from a UK online retailer
(December 2009 – December 2011), in one xlsx with two sheets (`Year 2009-2010`: 525,461 rows;
`Year 2010-2011`: 541,910) and the columns `Invoice`, `StockCode`, `Description`, `Quantity`,
`InvoiceDate`, `Price`, `Customer ID`, `Country`. 5,305 distinct products, 53,628 invoices,
1.83% of invoices are cancellations and 22.8% of rows carry no customer id. Free, no account,
plain HTTP download (`https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip`,
44 MB, verified reachable), so CI can fetch it without a secret.

Why it works for pricing: the same product is sold at several price points over time, so a
price–response curve is **identifiable**, and `Quantity` gives an outcome to maximise. `Price`
is what was charged on the line, not a list price.

Measured on the real download, after dropping returns, zero prices and cancelled invoices
(1,041,670 rows left): **88.6% of products have ≥2 price points, 77.6% have ≥3**, median 4,
and 99.2% of rows sit behind products with ≥2. The dataset clears the checklist below before
any modelling.

Two things F1 has to handle that only show up on the data: the `StockCode` column mixes
products with non-product lines — `DOT` (postage), `POST`, `M` (manual), `ADJUST`, `CRUK`,
`AMAZONFEE`, `BANK CHARGES`, single-letter and `PADS`-style codes — and some of them look like
the most price-variable products in the file (`DOT` shows 1,290 distinct "prices"), so an
unfiltered fit measures postage. And `Customer ID` is null on 22.8% of rows, which is fine for
per-product curves and not fine for per-customer segments.

Its one hard limit: **no propensities.** Nobody logged the probability of the price that was
charged, so the log cannot be used for off-policy evaluation as it stands. The pipeline
therefore fits demand on the real data (F1) and then simulates a bandit log with known
propensities on top of the fit (F2). Real data supplies the demand shape; the simulation
supplies the counterfactual.

Alternatives rejected:

- **M5 (Walmart)** — sell prices and promo flags, very clean, but distributed through Kaggle,
  which means credentials in CI for a dataset that never changes.
- **Corporación Favorita** — same Kaggle problem, larger than the exercise needs.
- **X5 RetailHero** — the sibling project `uplift-modeling-pipeline` already uses it, and two
  portfolio projects on one dataset reads as one project.

## Scale: the reference project, component by component

`uplift-modeling-pipeline` is the size to match. The equivalents:

| Reference (GCP) | Here (Azure) | Phase |
|---|---|---|
| DuckDB `ingest` + 8 parallel feature shards | DuckDB ingest + price–response per segment | F1 |
| Qini / AUUC evaluation | Regret, SNIPS replay, cumulative margin | F2 |
| T/X/S meta-learners on XGBoost | Thompson Sampling over price arms | F3 |
| MLflow server on Cloud Run + registry | MLflow hosted free on DagsHub + registry | F4 |
| `score.py` batch scoring to GCS | Simulation replay + posterior snapshot | F3 |
| FastAPI `POST /predict` on Cloud Run | FastAPI `GET /price`, `POST /reward` | F4 |
| Airflow DAG on a spot VM, manual trigger | GitHub Actions workflow, manual trigger | F7 |
| Terraform on GCP + Workload Identity Federation | Terraform `azurerm` + OIDC federated credentials | F6 |
| CI/CD: `dev`→staging, `main`→production | `dev`→staging; `main` publishes a versioned image | F7 |
| Grafana + drift job (PSI) | PSI on the traffic mix and the served price | F8 |
| Static demo page on Hugging Face | Price-curve demo per segment | F8 |

## Phases

### F0 · Foundations — done

Repo, uv project, lockfile, pytest, ruff, pre-commit hooks, CI with pinned action SHAs,
Dockerfile, and the `infra/` and `monitoring/` placeholders.

### F0.5 · Data contract and offline replay — done

`docs/data-contract.md` fixes the two events (`impression`, `reward`) with their attribution
rules, and `src/dp/simulate.py` replays a log: per-arm coverage, conversion, margin, and a
SNIPS estimate of what a fixed price would have earned on the same traffic.

### F1 · Ingest and demand model — `feat/data-and-demand`

- `scripts/fetch_data.sh` downloads the dataset into `data/raw/` (git-ignored).
- `src/dp/data.py`: DuckDB reads both sheets, drops cancellations, non-positive quantities
  and the non-product `StockCode`s named in the dataset section (postage, manual, adjustments),
  writes `data/processed/orders.parquet`.
- `src/dp/demand.py`: fits `log(quantity) ~ log(price)` per segment on a **time-based**
  held-out split, so the fit is never evaluated on the period it saw.
- Reports per segment: elasticity, R², the number of distinct prices behind it, and how many
  products were dropped for having a single price point.

Check: `uv run python -m dp.demand` prints the table, and a unit test on a hand-written CSV
fixture asserts the elasticity of a known curve. A product with one price is dropped, not
fitted — that is the failure this phase exists to prevent.

Measured on the real download (`python -m dp.data` 9s, `python -m dp.demand` 3s):

- 955,850 clean order lines become 126,354 (product, month, price) observations over 4,866
  products; dropped at ingest: 111,521 rows.
- 2,759 products fitted, 1,889 dropped for a single price point and 218 for too few
  observations.
- Median elasticity **−2.41** (p25 −3.21, p75 −1.75), 97.3% negative, median R² 0.53, median
  5 price points per product.
- Pooled behind a per-product intercept: −2.26, R² 0.46.
- Held out after 2011-05-01: median R² **0.26** over 2,273 products, and 66% beat predicting
  their own mean. The curve holds up for two products out of three and degrades for the rest.
- By price tier the elasticity is flat (q1 −2.27, q2 −2.30, q3 −2.31, q4 −2.14), so a
  product's price level is **not** a useful segment here — the product is. F2 calibrates per
  product and falls back to the tier only where a product has too little price variation.
- Bias to remember: prices moved in reaction to stock and season, not at random, so these
  magnitudes are an upper bound on the causal elasticity. The simulator treats them as the
  prior the bandit explores around, not as ground truth.

### F2 · Simulator with known propensities — `feat/simulator`

- `src/dp/simulate.py` gains a generator: sample demand from the F1 fit, log the arm that was
  served with its propensity, and emit a log in the `docs/data-contract.md` format.
- Policies replayed over the same log: the best fixed price (oracle), the modal price (what a
  real business would have charged), uniform random, and Thompson Sampling.
- Output: regret against the oracle, cumulative margin, share of oracle, and the number of
  requests each arm needed before the posterior settled.

Check: on a simulated log with a known optimum, the oracle wins by construction and Thompson
converges to it within the sample budget. That assertion is the phase.

Decisions closed here:

- **Arms are absolute prices**: five evenly spaced over each product's observed band
  (`price_min`..`price_max` from F1), not a global 1–100 grid.
- **One posterior per product, arms inside it**: a Beta per (product, arm) on conversion,
  scored by its unit margin. 50 products × 5 arms for the demo, not (arm × price tier).
- The data has no costs, so **variable cost is 50% of the modal price** (the price that sold
  the most units) and **conversion at the median price is 5%**; the curve gives the shape
  around that level. The cost was first anchored on the median price, which put the usual
  price of 4 of the 50 products below cost: a retailer does not sell most of its units at a
  loss, so the anchor moved to the modal price. Both are flags in
  `dp.simulate`, and every number below depends on them.

Measured (`uv run python -m dp.simulate`: top 50 products by units, 20,000 requests each,
same requests and same conversion draws for every policy):

| Policy | Expected margin | Regret | % of oracle |
|---|---|---|---|
| Oracle (best fixed arm per product) | 53,125 | 0 | 100% |
| Thompson Sampling | 49,981 | 3,144 | 94.1% |
| Modal price | 48,450 | 4,675 | 91.2% |
| Uniform | 33,395 | 19,730 | 62.9% |

- Arms span the 5th to 95th percentile of each product's observed prices. They first spanned
  min to max, and one sale far from the rest stretched a band (84879: 26.04 against a median
  of 1.69), which put most arms on prices the retailer barely used, made the usual price look
  poor (61.9% of the oracle) and inflated Thompson's lead over it to +52%. Within the real
  band the usual price is already the best arm in 41 of 50 products.
- Thompson's posterior-mean best arm settled on the oracle's in 45 of 50 products; median
  770 requests, p90 9,286. The five that did not settle have their two best arms within 2.2%
  of each other: their regret is small even when the choice flips.
- The oracle sits on the cheapest arm for 44 of 50 products. That is the F1 elasticities
  speaking (median −2.7 on these products, an upper bound): in the simulated world a lower
  price always sells enough more to pay for itself. The 91.2% for the modal price is a
  property of that world, not a claim about what the retailer left on the table.
- The uniform log (100,000 impressions, propensity 1/5) replays through the same
  `--events` path; on one product, SNIPS from it recovers each arm's true expected margin to
  within 0.02 (`tests/unit/test_simulator.py`).
- Thompson's own propensity is not logged yet: it has no closed form and needs a Monte Carlo
  estimate per request. That belongs to the serving policy in F3.

### F3 · Policy and store — `feat/thompson-policy`

- Real Thompson Sampling: one Beta posterior per (product, arm) on conversion, sample every
  arm, score by unit margin, argmax, clamp to `PRICE_MIN`/`PRICE_MAX`.
- The posterior lives in the store as one document per product with its arms inside, so a
  restart does not forget and a reward is a single atomic `incr` patch.
- `store.py` gets the Cosmos implementation of `record_event`, using `DefaultAzureCredential`
  (managed identity in Azure) — lazy and fail-open, and the whole suite must keep passing with
  no Azure credentials present. The dead Redis client and its dependency go in this phase.

Check: two sequential rewards move the posterior, and a restart preserves it.

Done (`tests/unit/test_dp.py`). What landed beyond the check:

- Without `COSMOS_ENDPOINT` the store runs the same code against an in-memory container,
  which is also the test double; nothing reaches the network at import.
- Fail-open on the request path: an unreachable store serves the uniform prior and a lost
  impression does not fail the quote. A reward that cannot be persisted raises, so F4 can
  answer 503.
- Thompson's propensity is the share of 1,000 posterior draws that pick the served arm.
- Not run against a real Cosmos account: `az` is not on this machine, so the `patch_item`
  `incr` on an array index is exercised only through the in-memory container until F6.

### F4 · Tracking, registry and the reward contract — `feat/mlflow-and-reward`

- MLflow: one parent run per pipeline execution and one child run per policy, with the demand
  model and the log attached; the feature table's SHA-256 logged as a parameter; only the best
  policy registered, as a new immutable version.
- `POST /reward`: idempotent by request id, rejects an arm that was never served, and answers
  **503** when the outcome cannot be persisted.
- `GET /health` for liveness and `GET /ready` for readiness, the latter naming the served
  policy version.

Check: through `TestClient`, a duplicated reward does not move the posterior twice and an
unknown arm comes back 4xx.

Done (`tests/integration/test_api.py`, `tests/unit/test_retrain.py`). What landed:

- `python -m dp.retrain` replaces the `scripts/retrain.py` placeholder: one parent run with
  `features_sha256` and `curves_sha256`, the curves and the log attached, one child per policy
  with regret, margin and share of oracle. The best policy other than the oracle (which needs
  the ground truth) is registered as a new version of `dynamic-pricing-policy`, its artifact
  being the catalogue. MLflow 3's `register_model` only takes logged models, so the version is
  created from the artifact directory with `create_model_version`.
- The catalogue is versioned in git (`src/dp/catalogue.json`, 50 products, 6 KB) and ships in
  the image, so the serving path still never reads the registry. A container answers `/ready`
  with 50 products instead of 404 on every price.
- `POST /reward` claims the reward id with an atomic create before touching the posterior, so
  two concurrent retries cannot both apply. If the posterior update fails, the claim is
  removed and the answer is 503, so the retry applies it. A reward outside its window is
  stored and not applied, as the data contract says.
- Tracking defaults to a local `sqlite:///mlflow.db`; DagsHub only needs
  `MLFLOW_TRACKING_URI` and a token, wired in F7.

### F5 · Serving limits and payload contract — `feat/serving-contract`

Small phase, and the one most projects skip: request size limits, a per-instance rate limit
answered with 429, and a response that names the policy version. It is the reference's
"Production limits" section, applied here. It is also where the price floor/ceiling violation
counter becomes a metric instead of an assumption.

Done, mirroring the reference's serving code: `X-API-Key` on `/price` and `/reward`, failing
closed when unset (an open `/reward` lets anyone steer prices; the key is the project's one
secret, a Container Apps secret); a per-replica token bucket answering 429 with `Retry-After`;
bodies over 4 KB refused with 413 before parsing; bounded `user_id`/`product`; `/metrics` with
latency per route, prices served per policy version, rewards by outcome and
`dp_price_guard_clamped_total`.

### F6 · Azure infrastructure — `feat/azure-infrastructure`

- Terraform `azurerm`: resource group, Container Apps environment and app (ingress target port
  **8000**, min replicas 0), Cosmos DB NoSQL provisioned at 1000 RU/s on the free tier, a
  managed identity with its Cosmos data-plane role assignment, and the API key as a Container
  Apps secret. One environment (`staging`). No Log Analytics: logs stream with
  `az containerapp logs show` during a demo, and nothing is ingested between demos.
- Verify with `terraform init && terraform validate`; `plan`/`apply` cannot run on a machine
  without `az` and must be reported as unverified rather than assumed.
- The account-level bootstrap is already written out in `infra/README.md`.

Done: `terraform validate` passes and `terraform plan` ran against the real subscription
(7 to add: Cosmos account with free tier and keys disabled, the `pricing` database at a shared
1000 RU/s, the `posteriors` and `events` containers, the Container Apps environment with no Log
Analytics, the app with a system-assigned identity, scale 0-1, liveness on `/health` and
readiness on `/ready`, and its Cosmos Built-in Data Contributor assignment). Not applied: the
image does not exist in GHCR until F7 publishes it. Bootstrap state on 2026-10-04: providers
registered and `rg-dp-staging` created; the OIDC app, federated credentials, role and GitHub
secrets are still to do.

### F7 · CI/CD and retraining — `feat/cicd-azure-deploy`

- `deploy.yml`, separate from `ci.yml`: push to `dev` builds the image, pushes it to GHCR with
  the workflow's own `GITHUB_TOKEN` and runs `az containerapp update`. `permissions: id-token:
  write`, a `concurrency` group, `environment: staging`, a preflight step that fails loudly on
  an empty variable, every action pinned to a full commit SHA.
- `retrain.yml`: `workflow_dispatch` only, running the pipeline and registering the policy in
  MLflow. The dataset never changes, so a weekly cron would spend CI minutes to reproduce the
  same numbers; the reference's DAG is manual-trigger for the same reason.
- `main` receives releases from `dev` and publishes a versioned image tag; there is no second,
  production Container App for an ephemeral demo stack to keep alive.

Done: `deploy.yml` builds with provenance and an SBOM and pushes `:<sha>` and `:<branch>` to
GHCR on `dev` and `main`; on `dev` it then logs in by OIDC, rolls the app onto `:<sha>` and
waits up to two minutes for `/ready` through the cold start. The deploy job is skipped while
`AZURE_CONTAINER_APP` is unset, and fails loudly on any other missing value. `retrain.yml`
caches the UCI download, refuses to run without a tracking server, and runs ingest, fit,
simulation and registration. Neither has run against Azure or DagsHub yet.

### F8 · Monitoring and demo — `feat/monitoring-demo`

- PSI on the traffic mix and on the served price distribution, against a
  `reference_profile.json` logged next to the registered policy — the reference project's drift
  job, applied to prices.
- A static demo page (Hugging Face Space, like the reference) showing the learned price curve
  and the posterior per segment, built from a precomputed replay so it needs no backend.

Done: `python -m dp.drift REFERENCE CURRENT` reports PSI on the product mix and on the served
arm position (0 cheapest to 4 dearest in a product's band), categorical so no bin edges, drift
above 0.2 as in the reference. `dp.retrain` registers `reference_profile.json` next to the
catalogue: what the registered policy served in simulation. On the uniform simulated log
against the registered Thompson reference: products PSI 0.000, arms PSI 0.662, drift, as it
should be, since a uniform policy is not the one registered. `demo/` is a static page over an
8 KB `data.json` written by `demo/make_data.py`; publishing it needs a Hugging Face account.

### F9 · Documentation reconciliation — `docs/azure-reality`

Update `README.md`, `PLAN.md`, `docs/architecture.md` and `infra/README.md` to describe what is
implemented, and fill in the Results table with real numbers.

## Success metrics

| Metric | Target | Measured |
|---|---|---|
| Thompson's share of the oracle's margin (simulated world, top 50 products) | at least 90% | 94.1% |
| Margin over the price the retailer usually charged | positive | +3.2% (49,981 vs 48,450), overtaking it after about 10,500 requests per product |
| p95 latency of `/price`, server side | below 50 ms | under 25 ms: 238 of 240 requests in the 25 ms bucket on staging (2026-10-05); the first request after a start took over 2.5 s while the Cosmos client and its token were created |
| Prices outside `PRICE_MIN`/`PRICE_MAX` | zero | zero by construction: clamped, and every clamp counted in `/metrics` |
| Fixed monthly cost | zero | zero: free tier, free grant, or destroyed after the demo |

## Reference

Structure, CI and conventions follow `uplift-modeling-pipeline`.
