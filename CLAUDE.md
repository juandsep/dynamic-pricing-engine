# CLAUDE.md

Instructions for coding agents working in this repository. Humans: `README.md`,
`PLAN.md` and `CONTRIBUTING.md` say the same things at more length.

## Where things stand

Read the `## Status` block of `PLAN.md` first: it names the merged phases, the next
one, and the numbers a fresh clone must reproduce. Each phase in `PLAN.md` has its
branch name and a check; the phase is done when the check passes, not when its files
exist. `README.md`, `PLAN.md`, `docs/architecture.md` and `infra/README.md` record
decisions already taken (Azure stack, arms per product, no Redis): reconcile them with
the code, do not reopen them without current prices from the Azure pricing API.

Closing a phase updates the `PLAN.md` Status block in the same pull request.

## Data

`data/` is git-ignored. Rebuild it before touching the models, and stop if the
numbers differ from `PLAN.md`:

```bash
scripts/fetch_data.sh          # 44 MB to data/raw/, skipped when present
uv run python -m dp.data       # orders.parquet
uv run python -m dp.demand     # demand curves and summary
uv run python -m dp.simulate   # policy table and simulated log
```

Traps already paid for:

- DuckDB `read_xlsx` dies on mixed types inside a column: read with
  `all_varchar = true` and cast in SQL. There is no `columns` parameter. With
  `all_varchar`, dates arrive as Excel serials (`1899-12-30 + serial * 86400`).
- `WITH` inside a `UNION ALL` branch is invalid SQL, and so is `CREATE TABLE AS WITH`.
- `StockCode` mixes products with `DOT`, `POST`, `M`, `ADJUST`, `AMAZONFEE`; keep
  `^\d{5}[A-Za-z]{0,3}$`.
- UCI throttles repeat downloads, which is why the file is cached in `data/raw/`.
- The F1 elasticities come from observational prices: they are an upper bound and a
  prior for the simulator, never ground truth.

## Rules

- Branches: cut from `dev`, one concern per branch and pull request, PRs into `dev`;
  `main` only receives PRs from `dev`. Never push to `main`.
- Conventional Commits in the imperative, with a body saying what changed and why.
- Everything in the repository is in English.
- Before each commit: `uv run ruff check . && uv run ruff format .`, `uv run pytest -q`,
  and the pre-commit hooks.
- Tests are fully offline: no Azure credentials, no network at import time. Cloud
  integrations are lazy and fail open.
- No Azure resource with a fixed monthly charge: free tier, inside a grant, or destroyed
  after use. No Redis, ACR, Key Vault, Cosmos serverless or self-hosted MLflow.
- No secrets in the repository and no cloud keys in CI: managed identity, data-plane
  RBAC, OIDC.
- This machine has no `az` CLI: never report a `terraform plan` or deploy that did not
  run. Subscription steps (login, federated credentials, role, GitHub secrets) are the
  owner's, listed in `infra/README.md`.
- Every "green" in a report comes from a command that actually ran.
