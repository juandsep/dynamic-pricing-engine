# Next-agent prompt — migrate the Dynamic Pricing Engine to Azure

Copy everything below the line into the next agent's first message.

---

CONTEXT

- Repository: `juandsep/dynamic-pricing-engine` (the local folder carries the same name).
  Work only inside that folder.
- Python project managed with **uv** (`pyproject.toml` + `uv.lock`). Console script: `uv run dp`.
- Branch model: `main` (releases) ← `dev` (integration) ← topic branches cut from `dev`.
  Cut your branch from `dev`; `main` only receives PRs from `dev`.
- Current state (all green: `uv run pytest -q` — 8 tests, `uv run ruff check .`,
  `uv run ruff format --check .`, docker build):
  - `src/dp/{__init__,api,thompson,store}.py` — FastAPI app with `/price` and `/health`,
    a Thompson Sampling placeholder (uniform draw inside `PRICE_MIN`/`PRICE_MAX`) and a
    feature-store wrapper with a Redis client (falls back to defaults when Redis is absent)
    and a `record_event` that raises `NotImplementedError`.
  - `tests/unit/` and `tests/integration/` (TestClient; no external services, no credentials).
  - `scripts/retrain.py`, `docker/Dockerfile` (multi-stage, non-root, healthcheck, `PORT=8000`),
    `docs/architecture.md`, `infra/`, `monitoring/`, `PLAN.md`, `CONTRIBUTING.md`.
  - `.github/workflows/ci.yml` — test job (`uv sync --locked`, ruff, pytest with coverage) and a
    docker build job; every action pinned to a full commit SHA.
- The target platform is Azure, but **nothing is deployed yet** and no cloud resource exists:
  `infra/` holds a README only, there is no deploy workflow and no Terraform state. The code
  still carries AWS assumptions: `boto3` and `feast` are declared dependencies and neither is
  imported anywhere.
- `README.md` and `docs/architecture.md` describe the **target** end state (Key Vault, Cosmos DB,
  Container Apps, `POST /reward`, price clamping), not what the code does today. Reconcile them
  against reality; never read them as a description of the current implementation.
- Reference for structure and conventions: `uplift-modeling-pipeline`, a sibling project in the
  same portfolio. Mirror its layout, its CONTRIBUTING conventions and its Dockerfile pattern.
  Note that it ships a **separate** `deploy.yml` next to `ci.yml`, not a deploy job inside it.

OBJECTIVE

Make the repository genuinely Azure-native: infrastructure as code, an Azure SDK based feature
store, and a CI/CD pipeline that builds, publishes and deploys. Leave no AWS assumption in the
repository.

STACK DECISIONS (use these)

- Compute: Azure Container Apps (preferred) or AKS.
- Images: Azure Container Registry.
- Online feature store: Azure Cache for Redis. Durable events: Azure Cosmos DB (NoSQL, serverless).
- Secrets: Azure Key Vault, read through a managed identity.
- Observability: Application Insights + Log Analytics.
- Model tracking: MLflow on Container Apps (or Azure ML), exposed through `MLFLOW_TRACKING_URI`.
- CI/CD: GitHub Actions authenticating with OIDC federated credentials — no stored cloud keys.

TASKS — as a sequence of pull requests, one concern each

Each group below is one branch cut from `dev` and one pull request into `dev`. Do not collapse them
into a single branch: one concern per branch and PR is a repository rule (`CONTRIBUTING.md`).
Report each PR as you land it.

PR 1 — `chore/azure-dependencies`

1. Replace the AWS dependencies: `uv remove boto3 feast`, then
   `uv add azure-identity azure-cosmos azure-keyvault-secrets`. Re-lock and confirm nothing
   imports the removed ones (`grep -rniE 'boto3|feast|dynamodb|elasticache' src tests` — no hits).

PR 2 — `feat/azure-feature-store`

2. Implement `FeatureStore.record_event` against Cosmos DB and read secrets from Key Vault.
   Keep the public interface (`get_features`, `set_features`) unchanged.
   - The Key Vault read must be **lazy and fail-open**: no network call at import time, no failure
     when `AZURE_KEYVAULT_URL` is unset, and no credential requirement in tests. The suite and the
     Docker build must keep passing with no Azure credentials present — an acceptance condition,
     not a nicety.
   - Authenticate with `DefaultAzureCredential` (managed identity in Azure); never a stored key.

PR 3 — `feat/thompson-policy-and-reward`

3. Implement the real policy in `thompson.py`: one Beta posterior per (price arm, segment), sample
   every arm, return the argmax, clamp to `PRICE_MIN` / `PRICE_MAX`.
   - Posteriors live in **Azure Cache for Redis**, not in process memory: Container Apps runs
     several replicas, and an in-memory posterior means each replica learns separately.
     `docs/architecture.md` already specifies Redis as the store.
4. Add `POST /reward` so observed outcomes update the posterior and are written to Cosmos DB.
   State the contract in the PR: request body schema, rejection of a reward for an arm that was
   never served, an idempotency key so a retried reward cannot update the posterior twice, and
   whether the Cosmos write happens before or after the 200.

PR 4 — `feat/azure-infrastructure`

5. Replace `infra/` with Terraform (`azurerm`): `main.tf`, `variables.tf`, `outputs.tf`,
   `terraform.tfvars.example` covering ACR, Container Apps environment and app, Azure Cache for
   Redis, Cosmos DB, Key Vault and Log Analytics.
   - Declare `required_providers` with a pinned `azurerm` version.
   - The Container App ingress target port must be **8000**, matching `docker/Dockerfile`
     (`ENV PORT=8000`); a probe against the wrong port fails the revision.
   - Verify with `terraform init && terraform validate` inside `infra/` (`validate` alone fails
     without `init`). `infra/terraform.tfvars`, `infra/*.tfstate` and `infra/.terraform/` are
     already git-ignored.
   - This machine has no `az` CLI, so `terraform plan`/`apply` and `az containerapp update` cannot
     be exercised locally. Say so plainly instead of reporting a plan that never ran.

PR 5 — `feat/cicd-azure-deploy`

6. Add `.github/workflows/deploy.yml`, separate from `ci.yml`, mirroring the reference project's
   deploy workflow: triggered by pushes to `dev`, with `permissions: id-token: write` (required by
   `azure/login` OIDC — without it the login fails), a `concurrency` group, an
   `environment: staging`, and a preflight step that fails loudly when a required variable is
   empty. Pin every action to a full commit SHA, as `ci.yml` does.
   - Build and push the image to ACR, then `az containerapp update`.
   - Pin the served policy version through an explicit variable (the reference project does this
     with `MODEL_VERSION`); never a floating alias (`CONTRIBUTING.md`).
7. Add `.github/workflows/retrain.yml`: a scheduled job with an explicit cron expression running
   `uv run python scripts/retrain.py` and registering the recalibrated policy in MLflow.
   - Add `workflow_dispatch` so the job can be run on demand, and list the variables and secrets it
     needs (`MLFLOW_TRACKING_URI`, Cosmos endpoint) behind the same preflight guard.

PR 6 — `docs/azure-reality`

8. Update `README.md`, `PLAN.md`, `docs/architecture.md` and `infra/README.md` to describe what is
   implemented: reconcile the aspirational sections, the environment-variable table and the
   `POST /reward` contract with the code.
9. Delete `PROMPT_NEXT_AGENT.md` in this PR. The migration prompt must not survive the migration,
   and acceptance criterion 4 cannot hold while it does.

Verify in PR 6: `uv sync --locked`, `uv run ruff check . && uv run ruff format --check .`,
`uv run pytest -q`, `docker build -f docker/Dockerfile -t dynamic-pricing-engine:ci .` and
`terraform init && terraform validate` inside `infra/`.

RULES

- Everything in the repository is written in **English** (code, comments, docs, commits).
- Conventional Commits, imperative mood. One concern per branch and per PR.
- No secrets in the repository and no cloud keys in CI: Key Vault, managed identity, OIDC.
- Never push directly to `main`; open a PR into `dev`.
- Every green claim in your report must come from a command you actually ran, with its real output.

ACCEPTANCE CRITERIA

- `uv run pytest -q`, `uv run ruff check .` and `uv run ruff format --check .` pass, and the Docker
  image builds — with no Azure credentials and no reachable cloud service.
- `terraform validate` passes for the Azure configuration (after `terraform init`).
- CI publishes to ACR and updates the Container App on `dev`, authenticated through OIDC.
- No file in the repository mentions AWS, ECS, ECR, ElastiCache or DynamoDB. Checked after PR 6,
  which deletes `PROMPT_NEXT_AGENT.md` — today the only remaining place those words appear, next
  to `pyproject.toml`.
