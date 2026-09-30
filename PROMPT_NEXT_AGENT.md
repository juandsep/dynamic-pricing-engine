# Next-agent prompt — migrate the Dynamic Pricing Engine to Azure

Copy everything below the line into the next agent's first message.

---

CONTEXT

- Repository: `juandsep/dynamic-pricing-engine` (the local folder carries the same name).
  Work only inside that folder.
- Python project managed with **uv** (`pyproject.toml` + `uv.lock`). Console script: `uv run dp`.
- Branch model: `main` (releases) ← `dev` (integration) ← topic branches cut from `dev`.
  Cut your branch from `dev`; `main` only receives PRs from `dev`.
- Current state (all green: `uv run pytest -q`, `uv run ruff check .`, docker build):
  - `src/dp/{__init__,api,thompson,store}.py` — FastAPI app with `/price` and `/health`,
    a Thompson Sampling placeholder and a feature-store wrapper with a Redis client
    (falls back to defaults when Redis is absent) and a Cosmos DB writer placeholder.
  - `tests/unit/` and `tests/integration/` (TestClient, no external services).
  - `scripts/retrain.py`, `docker/Dockerfile` (multi-stage, non-root, healthcheck),
    `docs/architecture.md`, `infra/`, `monitoring/`, `PLAN.md`, `CONTRIBUTING.md`.
  - `.github/workflows/ci.yml` — test job (uv sync --locked, ruff, pytest) and a docker build job.
- The project is hosted on Azure as of this task, but the code and dependencies still
  carry AWS assumptions: `boto3` is a dependency, and `infra/` only contains documentation.
- Reference for structure and conventions: the `uplift-modeling-pipeline` project of the
  same portfolio. Mirror its layout, its CI shape, its CONTRIBUTING conventions and its
  Dockerfile pattern.

OBJECTIVE

Make the repository genuinely Azure-native: infrastructure as code, an Azure SDK based
feature store, and a CI/CD pipeline that builds, publishes and deploys. Leave no AWS
assumption in the repository.

STACK DECISIONS (use these)

- Compute: Azure Container Apps (preferred) or AKS.
- Images: Azure Container Registry.
- Online feature store: Azure Cache for Redis. Durable events: Azure Cosmos DB (NoSQL, serverless).
- Secrets: Azure Key Vault, read through a managed identity.
- Observability: Application Insights + Log Analytics.
- Model tracking: MLflow on Container Apps (or Azure ML), exposed through `MLFLOW_TRACKING_URI`.
- CI/CD: GitHub Actions authenticating with OIDC federated credentials — no stored cloud keys.

TASKS (in order)

1. Cut `chore/azure-migration` from `dev`.
2. Replace the AWS dependencies: `uv remove boto3 feast`, then
   `uv add azure-identity azure-cosmos azure-keyvault-secrets`. Re-lock and confirm
   nothing else imports them (`grep -rn boto3 src tests`).
3. Implement `FeatureStore.record_event` against Cosmos DB and read secrets from Key Vault
   at startup. Keep the public interface (`get_features`, `set_features`) unchanged.
4. Implement the real policy in `thompson.py`: one Beta posterior per (price arm, segment),
   sample every arm, return the argmax, and clamp to `PRICE_MIN` / `PRICE_MAX`.
   Add `POST /reward` so observed outcomes update the posterior and are written to Cosmos DB.
5. Replace `infra/` with Terraform (`azurerm`): `main.tf`, `variables.tf`, `outputs.tf`,
   `terraform.tfvars.example` covering ACR, Container Apps environment and app, Azure Cache
   for Redis, Cosmos DB, Key Vault and Log Analytics. Run `terraform validate`.
6. Extend `.github/workflows/ci.yml` with a deploy job (ACR push + `az containerapp update`)
   that runs only on pushes to `dev`, using OIDC (`azure/login`). Pin every action to a full
   commit SHA, as the existing CI does.
7. Add `.github/workflows/retrain.yml`: weekly cron running `uv run python scripts/retrain.py`
   and registering the recalibrated policy in MLflow.
8. Update `README.md`, `PLAN.md` and `docs/architecture.md` to match reality; keep them in English.
9. Verify locally: `uv sync --locked`, `uv run ruff check . && uv run ruff format --check .`,
   `uv run pytest -q`, `docker build -f docker/Dockerfile -t dynamic-pricing-engine:ci .`
   and `terraform validate` inside `infra/`.

RULES

- Everything in the repository is written in **English** (code, comments, docs, commits).
- Conventional Commits, imperative mood. One concern per branch and PR.
- No secrets in the repository and no cloud keys in CI: Key Vault, managed identity, OIDC.
- Never push directly to `main`; open a PR into `dev`.
- Report what you changed, the exact commands you ran and their real output. Do not
  describe results you did not produce.

ACCEPTANCE CRITERIA

- No file in the repository mentions AWS, ECS, ECR, ElastiCache or DynamoDB.
- `terraform validate` passes for the Azure configuration.
- `uv run pytest -q` and `uv run ruff check .` pass; the Docker image builds.
- CI publishes to ACR and updates the Container App on `dev`, authenticated through OIDC.
