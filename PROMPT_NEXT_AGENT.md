# Next-agent prompt — migrate the Dynamic Pricing Engine to Azure

Copy everything below the line into the next agent's first message.

---

CONTEXT

- Repository: `juandsep/dynamic-pricing-engine` (the local folder carries the same name).
  Work only inside that folder.
- Python project managed with **uv** (`pyproject.toml` + `uv.lock`). Console script: `uv run dp`.
- Branch model: `main` (releases) ← `dev` (integration) ← topic branches cut from `dev`.
  Cut your branch from `dev`; `main` only receives PRs from `dev`.
- Current state (all green: `uv run pytest -q`, `uv run ruff check .`,
  `uv run ruff format --check .`, docker build):
  - `src/dp/{__init__,api,thompson,store}.py` — FastAPI app with `/price` and `/health`,
    a Thompson Sampling placeholder (uniform draw inside `PRICE_MIN`/`PRICE_MAX`) and a
    feature-store wrapper that still carries an unused Redis client plus a `record_event`
    that raises `NotImplementedError`.
  - `src/dp/simulate.py` — offline replay of a logged policy: validates the log, joins
    rewards onto impressions, reports per-arm coverage/conversion/margin and a SNIPS
    estimate of a fixed-price baseline. Stdlib only.
  - `tests/unit/` and `tests/integration/` (TestClient; no external services, no credentials).
  - `scripts/retrain.py`, `docker/Dockerfile` (multi-stage, non-root, healthcheck, `PORT=8000`),
    `docs/architecture.md`, `docs/data-contract.md`, `infra/`, `monitoring/`, `PLAN.md`,
    `CONTRIBUTING.md`.
  - `.github/workflows/ci.yml` — test job (`uv sync --locked`, ruff, pytest with coverage) and a
    docker build job; every action pinned to a full commit SHA.
- The target platform is Azure, but **nothing is deployed yet** and no cloud resource exists:
  `infra/` holds a README only, there is no deploy workflow and no Terraform state. The code
  still carries AWS assumptions: `boto3` and `feast` were declared dependencies, imported
  nowhere; both were removed with the data phase. `redis` is still declared and still
  referenced by `src/dp/store.py`, and goes when that store is rewritten.
- `README.md`, `PLAN.md`, `docs/architecture.md` and `infra/README.md` describe the **target** end
  state (Cosmos DB, Container Apps, `POST /reward`, price clamping), not what the code does today.
  Reconcile them against reality; never read them as a description of the current implementation.
  They do define the intended architecture and the cost envelope — do not re-open those decisions.
- Reference for structure and conventions: `uplift-modeling-pipeline`, a sibling project in the
  same portfolio. Mirror its layout, its CONTRIBUTING conventions and its Dockerfile pattern.
  Note that it ships a **separate** `deploy.yml` next to `ci.yml`, not a deploy job inside it.
  It is a GCP project: mirror its *conventions*, not its providers.

OBJECTIVE

Make the repository genuinely Azure-native: infrastructure as code, an Azure SDK based feature
store, and a CI/CD pipeline that builds, publishes and deploys. Leave no AWS assumption in the
repository. Keep the monthly cost at zero.

STACK DECISIONS (use these; they are settled, with the price that decided each one)

- Compute: **Azure Container Apps**, consumption plan, minimum replicas 0. Free grant: the first
  180,000 vCPU-seconds, 360,000 GiB-seconds and 2M requests per subscription per calendar month.
  A revision scaled to zero is not billed.
- Region: **`eastus2`**. Container Apps bills 2.4e-05 USD per vCPU-second and 3e-06 per
  GiB-second there; `spaincentral` and `westeurope` bill 3.4e-05 and 4e-06 — about 42 % more.
- Images: **GHCR**, public package, pulled anonymously. Azure Container Registry Basic costs
  0.1666 USD/day (~5.03 USD/month) and bills even with nothing deployed, so there is no ACR.
- Store: **Azure Cosmos DB (NoSQL), provisioned 1000 RU/s, free tier opted into at account
  creation** — the first 1000 RU/s and 25 GB are free for the lifetime of the account, one account
  per subscription. It holds the posterior, the durable events and the attributes.
  **Free tier does not apply to serverless accounts**; do not create a serverless account.
- No Redis. Azure Cache for Redis Basic C0 costs 0.0275 USD/hour (~20 USD/month) and the service
  runs a single replica, where the posterior document in Cosmos is equivalent. `docs/architecture.md`
  carries the `ponytail:` marker with the upgrade path.
- No Key Vault, and no secrets anywhere: the app authenticates to Cosmos with its **managed identity**
  plus a Cosmos data-plane role assignment, and CI authenticates with **OIDC federated credentials**.
- Model tracking: **MLflow hosted free on DagsHub** (`MLFLOW_TRACKING_URI` +
  `MLFLOW_TRACKING_USERNAME`/`MLFLOW_TRACKING_PASSWORD` from a GitHub secret). Self-hosted MLflow
  would need an always-on backend (~15-20 USD/month), Azure ML would not be free either.
- Observability: Application Insights and Log Analytics are optional at this stage; the free
  ingestion grant covers a demo by orders of magnitude. The Container Apps environment also accepts
  `--logs-destination none`, which removes the workspace entirely.
- Everything is **ephemeral**: `terraform apply` before a demo, `terraform destroy` after. Terraform
  state stays local (`infra/*.tfstate` is git-ignored); a remote state storage account would be the
  one resource nobody ever destroys.
- **Budget: a subscription budget fixed at 10 USD/month, with notifications at 50 %, 90 % and 100 %.**
  It is set with the Azure CLI, outside Terraform, and it is a tripwire rather than a hard stop
  (an Azure budget only alerts). A non-zero bill means a resource outlived its demo.
- Do not add a resource whose cost is debated in the PR. If you believe one of the rejections above
  is wrong, say so with the current price from the Azure retail prices API and let the human decide.

TASKS — as a sequence of pull requests, one concern each

Each group below is one branch cut from `dev` and one pull request into `dev`. Do not collapse them
into a single branch: one concern per branch and PR is a repository rule (`CONTRIBUTING.md`).
Report each PR as you land it.

The order to follow is `PLAN.md` (F1–F9), which is kept current; the two PRs below are the
Azure half of it in more words. Where they disagree, `PLAN.md` wins — F1 already removed
`boto3` and `feast`.

PR 1 — `chore/azure-dependencies`

1. Replace the AWS dependencies: `uv remove redis`, then `uv add azure-identity azure-cosmos`.
   Re-lock and confirm nothing imports the removed ones
   (`grep -rniE 'boto3|feast|dynamodb|elasticache' src tests` — no hits). Do not add
   `azure-keyvault-secrets`: there is no key vault and no secret in this design.

PR 2 — `feat/azure-feature-store`

2. Implement `FeatureStore.record_event` against Cosmos DB. Keep the published interface
   (`get_features`, `set_features`) unchanged, and delete the Redis client and the `REDIS_URL`
   handling while you are in the file — it is dead code once the dependency is gone.
   - Authenticate with `DefaultAzureCredential` (managed identity in Azure); never a stored key.
     The endpoint comes from `COSMOS_ENDPOINT` / `COSMOS_DATABASE`, and a missing endpoint must be
     **lazy and fail-open**: no network call at import time, no failure when the variables are
     unset, no credential requirement in tests. The suite and the Docker build must keep passing
     with no Azure credentials present — an acceptance condition, not a nicety.
   - Idempotency and the event schema are already defined in `docs/data-contract.md`. Implement
     them as written; if the contract is wrong, change the contract in the same PR and say why.

PR 3 — `feat/thompson-policy-and-reward`

3. Implement the real policy in `thompson.py`: one Beta posterior per (price arm, segment), sample
   every arm, return the argmax, clamp to `PRICE_MIN` / `PRICE_MAX`.
   - Posteriors live in the **store**, not in process memory, as one document per (arm, segment).
     The service runs one replica, so the store is what keeps learning consistent across restarts;
     `docs/architecture.md` states the reasoning and the ceiling.
4. Add `POST /reward` so observed outcomes update the posterior and are written to Cosmos DB.
   State the contract in the PR: request body schema, rejection of a reward for an arm that was
   never served, an idempotency key so a retried reward cannot update the posterior twice, and
   whether the Cosmos write happens before or after the 200. A reward that cannot be persisted is
   **503**, never a silent 200 (`docs/architecture.md`, *Failure behaviour*).
5. Log the retrained policy and its metrics to MLflow at `MLFLOW_TRACKING_URI`. The serving path
   must not read the registry at runtime — it reads the posterior from the store — so the service
   needs no tracking credentials at all.

PR 4 — `feat/azure-infrastructure`

6. Replace `infra/` with Terraform (`azurerm`): `main.tf`, `variables.tf`, `outputs.tf`,
   `terraform.tfvars.example` covering the resource group, the Container Apps environment and app,
   Cosmos DB (NoSQL, provisioned 1000 RU/s, free tier enabled), the managed identity with its Cosmos
   data-plane role assignment, and optionally Log Analytics and Application Insights.
   - Declare `required_providers` with a pinned `azurerm` version.
   - The Container App ingress target port must be **8000**, matching `docker/Dockerfile`
     (`ENV PORT=8000`); a probe against the wrong port fails the revision.
   - The image is a public GHCR package: no registry credentials in the app configuration.
   - Verify with `terraform init && terraform validate` inside `infra/` (`validate` alone fails
     without `init`). `infra/terraform.tfvars`, `infra/*.tfstate` and `infra/.terraform/` are
     already git-ignored.
   - This machine has no `az` CLI, so `terraform plan`/`apply` and `az containerapp update` cannot
     be exercised locally. Say so plainly instead of reporting a plan that never ran.

PR 5 — `feat/cicd-azure-deploy`

7. Add `.github/workflows/deploy.yml`, separate from `ci.yml`, mirroring the reference project's
   deploy workflow: triggered by pushes to `dev`, with `permissions: id-token: write` (required by
   `azure/login` OIDC — without it the login fails) plus `packages: write` to publish to GHCR, a
   `concurrency` group, an `environment: staging`, and a preflight step that fails loudly when a
   required variable is empty. Pin every action to a full commit SHA, as `ci.yml` does.
   - Build and push the image to GHCR with the built-in `GITHUB_TOKEN` (no new secret), then
     `az containerapp update`.
   - Pin the served policy version through an explicit variable (the reference project does this
     with `MODEL_VERSION`); never a floating alias (`CONTRIBUTING.md`).
8. Add `.github/workflows/retrain.yml`: a scheduled job with an explicit cron expression running
   `uv run python scripts/retrain.py` and registering the recalibrated policy in MLflow.
   - Add `workflow_dispatch` so the job can be run on demand, and list the variables and secrets it
     needs behind the same preflight guard: `MLFLOW_TRACKING_URI`, `MLFLOW_TRACKING_USERNAME`,
     `MLFLOW_TRACKING_PASSWORD`, `COSMOS_ENDPOINT`.

PR 6 — `docs/azure-reality`

9. Update `README.md`, `PLAN.md`, `docs/architecture.md` and `infra/README.md` to describe what is
   implemented: reconcile the aspirational sections, the environment-variable table and the
   `POST /reward` contract with the code.
10. Delete `PROMPT_NEXT_AGENT.md` in this PR. The migration prompt must not survive the migration,
    and acceptance criterion 4 cannot hold while it does.

Verify in PR 6: `uv sync --locked`, `uv run ruff check . && uv run ruff format --check .`,
`uv run pytest -q`, `docker build -f docker/Dockerfile -t dynamic-pricing-engine:ci .` and
`terraform init && terraform validate` inside `infra/`.

RULES

- Everything in the repository is written in **English** (code, comments, docs, commits).
- Conventional Commits, imperative mood. One concern per branch and per PR.
- **No Azure resource may carry a fixed monthly charge.** Everything is free-tier, inside a
  per-subscription free grant, or destroyed while idle. A PR that introduces a recurring line item
  is rejected even if it is technically correct.
- No secrets in the repository and no cloud keys in CI: managed identity, data-plane RBAC, OIDC.
- Never push directly to `main`; open a PR into `dev`.
- Every green claim in your report must come from a command you actually ran, with its real output.

ACCEPTANCE CRITERIA

- `uv run pytest -q`, `uv run ruff check .` and `uv run ruff format --check .` pass, and the Docker
  image builds — with no Azure credentials and no reachable cloud service.
- `terraform validate` passes for the Azure configuration (after `terraform init`).
- CI publishes the image to GHCR and updates the Container App on `dev`, authenticated through OIDC.
- No resource in `infra/` has a fixed monthly cost, and no file in the repository provisions Redis,
  ACR, Key Vault, serverless Cosmos or a self-hosted MLflow backend.
- No file in the repository mentions AWS, ECS, ECR, ElastiCache or DynamoDB. Checked after PR 6,
  which deletes `PROMPT_NEXT_AGENT.md` — today the only remaining place those words appear, next
  to `pyproject.toml`.
