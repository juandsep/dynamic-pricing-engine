# Infrastructure — Dynamic Pricing Engine (Azure)

Terraform (`azurerm`) provisioning the resources the service needs. Every resource here is free-tier
or inside a per-subscription free grant: the running bill is **0 USD/month** and there is no fixed
line item. The prices behind the rejections below come from the Azure retail prices API.

| Resource | Purpose | Cost |
|---|---|---|
| Container Apps Environment + App | runtime, ingress and revisions; 0 to 1 replica, 0.25 vCPU / 0.5 GiB | 0 — inside the monthly free grant (180,000 vCPU-s, 360,000 GiB-s, 2M requests per subscription) |
| Azure Cosmos DB (NoSQL, **provisioned 1000 RU/s** shared at database level, free tier enabled at creation, keys disabled) | `posteriors` and `events` containers | 0 — free tier covers the first 1000 RU/s and 25 GB for the lifetime of the account, one account per subscription |
| Managed identity + Cosmos data-plane role assignment | lets the app read and write Cosmos with no connection string | 0 |

Deliberately **not** provisioned, and why:

| Rejected | Would cost | Replacement |
|---|---|---|
| Azure Cache for Redis (Basic C0) | ~20 USD/month, fixed | the posterior document in Cosmos DB (one replica; see `docs/architecture.md`) |
| Azure Container Registry (Basic) | ~5.03 USD/month, billed even with nothing deployed | GHCR public package, pulled anonymously |
| Azure Key Vault | ~0, but a service and a code path | managed identity to Cosmos, OIDC in CI; the API key is a Container Apps secret |
| MLflow on Container Apps + Azure Files/PostgreSQL | ~15-20 USD/month, fixed | MLflow hosted free on DagsHub |
| Cosmos DB **serverless** | per-RU billing | provisioned 1000 RU/s — free tier does not apply to serverless accounts |

## Layout

```
infra/
├─ versions.tf                # Terraform and azurerm versions, provider, local state
├─ main.tf                    # Cosmos account, database and containers; Container Apps
│                             # environment and app; the app's data-plane role
├─ variables.tf               # inputs (subscription, names, image, API key, throughput)
├─ outputs.tf                 # app URL, Container App name, Cosmos endpoint
└─ terraform.tfvars.example   # copy to terraform.tfvars and fill in
```

## Usage

```bash
cd infra
terraform init
terraform validate
terraform plan  -var-file=terraform.tfvars
terraform apply -var-file=terraform.tfvars
```

`terraform.tfvars` is git-ignored. There is one environment, `staging`, deployed from `dev`: an
ephemeral stack has no traffic that a second, production copy would protect. Releases to `main`
publish a versioned image instead of a second Container App.

**Ephemeral by design.** Resources are applied before a demo or a screenshot session and destroyed
afterwards:

```bash
terraform destroy -var-file=terraform.tfvars
```

Free grants cover the running hours; destroying removes the ones that bill while idle. Terraform
state stays local (`infra/*.tfstate` is git-ignored) because a state storage account would be the
only resource nobody ever destroys.

## Bootstrap (one-off, by hand)

Terraform provisions the stack. The steps below cannot be done by it — they are account-level —
and they are the only manual work in this repository. Run them once per subscription.

### 1. Sign in and pin the subscription

```bash
brew install azure-cli
az login
az account list --query "[].{name:name, id:id, state:state}" -o table
az account set --subscription "<subscription-id-or-name>"

export SUB_ID=$(az account show --query id -o tsv)
export TENANT_ID=$(az account show --query tenantId -o tsv)
```

Everything after this runs against that subscription. Confirm `SUB_ID` is the one you expect before
the next step: every command below writes to whatever `az account show` reports.

### 2. Register the resource providers

Once per subscription; the first `terraform apply` is noisy and slow without it.

```bash
for ns in Microsoft.App Microsoft.DocumentDB Microsoft.OperationalInsights \
          Microsoft.Insights Microsoft.ManagedIdentity; do
  az provider register --namespace "$ns" --wait
done
```

### 3. Resource group

```bash
az group create --name rg-dp-staging --location eastus2
```

`eastus2` because Container Apps bills 2.4e-05 USD per vCPU-second there against 3.4e-05 in
`spaincentral` and `westeurope` (~42 % more).

### 4. Budget: fixed at 10 USD/month

```bash
export ALERT_EMAIL="you@example.com"

cat > budget.json <<EOF
{
  "properties": {
    "category": "Cost",
    "amount": 10,
    "timeGrain": "Monthly",
    "timePeriod": { "startDate": "2026-10-01T00:00:00Z", "endDate": "2030-12-31T00:00:00Z" },
    "notifications": {
      "actual-50-percent":      { "enabled": true, "operator": "GreaterThan", "threshold": 50,  "thresholdType": "Actual",     "contactEmails": ["$ALERT_EMAIL"] },
      "actual-90-percent":      { "enabled": true, "operator": "GreaterThan", "threshold": 90,  "thresholdType": "Actual",     "contactEmails": ["$ALERT_EMAIL"] },
      "forecasted-100-percent": { "enabled": true, "operator": "GreaterThan", "threshold": 100, "thresholdType": "Forecasted", "contactEmails": ["$ALERT_EMAIL"] }
    }
  }
}
EOF

az rest --method put \
  --url "https://management.azure.com/subscriptions/$SUB_ID/providers/Microsoft.Consumption/budgets/dp-10usd?api-version=2023-11-01" \
  --body @budget.json

rm budget.json
```

Use this rather than `az consumption budget create`. That subcommand exists, but at
subscription scope it **cannot express the notifications block** — `--notifications` is only on
`create-with-rg` — so the budget it creates never tells anyone anything. The REST call above is
Microsoft's documented automation path and carries the thresholds in the same request, so there is
no portal step afterwards.

The API enforces the rules: `startDate` must be the first day of the month, up to five
notifications per budget, `threshold` is a percentage between 0 and 1000, and at subscription scope
`contactEmails` is required. `2019-10-01` also works if your CLI is pinned to an older API version.

Confirm it exists and carries the alerts:

```bash
az rest --method get \
  --url "https://management.azure.com/subscriptions/$SUB_ID/providers/Microsoft.Consumption/budgets/dp-10usd?api-version=2023-11-01" \
  --query "properties.{amount:amount, notifications:notifications}" -o json
```

This is a tripwire, not a hard stop: **an Azure budget only alerts, it never stops spending**. The
target for this stack is 0 USD, so any figure above 0 means a resource outlived its demo — look for a
leftover Container Apps environment or Cosmos account before touching the budget. A budget is deleted
automatically when it expires, which is why the end date is far out.


### 5. GitHub Actions identity (OIDC, no stored keys)

```bash
APP_NAME="gh-dynamic-pricing-engine"
APP_ID=$(az ad app create --display-name "$APP_NAME" --query appId -o tsv)
az ad sp create --id "$APP_ID"          # no-op error is fine if it already exists

cat > fc-dev.json <<EOF
{"name": "github-dev",
 "issuer": "https://token.actions.githubusercontent.com",
 "subject": "repo:juandsep/dynamic-pricing-engine:ref:refs/heads/dev",
 "audiences": ["api://AzureADTokenExchange"]}
EOF

cat > fc-staging.json <<EOF
{"name": "github-environment-staging",
 "issuer": "https://token.actions.githubusercontent.com",
 "subject": "repo:juandsep/dynamic-pricing-engine:environment:staging",
 "audiences": ["api://AzureADTokenExchange"]}
EOF

az ad app federated-credential create --id "$APP_ID" --parameters fc-dev.json
az ad app federated-credential create --id "$APP_ID" --parameters fc-staging.json
rm fc-dev.json fc-staging.json
```

**Both credentials are required.** The deploy job declares `environment: staging`, and GitHub then
stamps the token's `sub` claim with the *environment*, not the branch — a credential that only trusts
`ref:refs/heads/dev` is rejected by `azure/login` with an unhelpful error. Create whichever
credentials match the workflow as written.

### 6. Role assignment

```bash
az role assignment create \
  --assignee "$APP_ID" \
  --role "Contributor" \
  --scope "/subscriptions/$SUB_ID/resource-groups/rg-dp-staging"
```

Contributor on the resource group, not on the subscription, and never Owner. CI only needs to update
the Container App; if you want it narrower, `Container Apps Contributor` on the same scope is enough
and you can drop Contributor.

### 7. GitHub secrets

```bash
gh secret set AZURE_CLIENT_ID     --body "$APP_ID"
gh secret set AZURE_TENANT_ID     --body "$TENANT_ID"
gh secret set AZURE_SUBSCRIPTION_ID --body "$SUB_ID"
```

The deploy job also reads two repository variables; it is skipped while they are unset:

```bash
gh variable set AZURE_RESOURCE_GROUP --body rg-dp-staging
gh variable set AZURE_CONTAINER_APP  --body dp-staging-api   # terraform output container_app
```

Nothing else for Azure. The image goes to GHCR with the workflow's own `GITHUB_TOKEN`, and the app
reaches Cosmos with its managed identity, so there is no registry credential and no connection
string.

The first push to `dev` after the deploy workflow lands publishes the image. GHCR creates the
package **private**; make it public once (package settings → *Change visibility*) so the Container
App can pull it anonymously.

Tracking for `retrain.yml` (manual trigger) is DagsHub's free MLflow server:

```bash
gh variable set MLFLOW_TRACKING_URI      --body https://dagshub.com/<user>/<repo>.mlflow
gh variable set MLFLOW_TRACKING_USERNAME --body <user>
gh secret   set MLFLOW_TRACKING_PASSWORD  # a DagsHub access token
```

### 8. Then Terraform

Apply after the first image is in GHCR and the package is public: the Container App pulls it
when it is created.

```bash
cd infra && cp terraform.tfvars.example terraform.tfvars   # subscription id and API key
terraform init && terraform validate
terraform plan  -var-file=terraform.tfvars && terraform apply -var-file=terraform.tfvars
terraform output url
```

The Cosmos account must be created with the free tier enabled: **one free-tier account per
subscription and the opt-in only exists at creation time**, so if the subscription already has one,
`apply` fails on that property and the design needs a decision rather than a workaround.

### 9. Teardown

```bash
terraform destroy -var-file=terraform.tfvars
```

Then confirm nothing survives:

```bash
az resource list --resource-group rg-dp-staging -o table
az consumption budget show --budget-name dp-10usd -o table
az ad app federated-credential list --id "$APP_ID" -o table
az role assignment list --assignee "$APP_ID" --all -o table
```

## Conventions

- One module per resource group concern. The layout in this repository is the reference for Azure;
  `portfolio-infra` is GCP-only (`google` providers) and must not be mirrored here.
- No cloud credentials in state or anywhere else. Workloads authenticate with managed identities
  and data-plane role assignments; CI authenticates to Azure through OIDC federated credentials.
  The API key is a Container Apps secret, passed as a sensitive variable and never committed.
- No Log Analytics workspace is provisioned: `az containerapp logs show`
  streams the console during a demo, and nothing ingests or retains logs between demos.
- Region: `eastus2`. Container Apps bills 2.4e-05 USD per vCPU-second and 3e-06 per GiB-second there;
  `spaincentral` and `westeurope` bill 3.4e-05 and 4e-06, about 42 % more on the same workload.
- Cosmos throughput is fixed at 1000 RU/s (the free-tier ceiling). A burst above it returns 429s;
  the upgrade path is autoscale, then serverless — both of which start billing.
- **Budget: fixed at 10 USD/month** for the subscription, with notifications at 50 %, 90 % and 100 %.
  It is a tripwire, not a hard stop — an Azure budget only alerts. It is configured with the CLI and
  not by Terraform, because it is an account-level guard rather than a resource of this stack.
  Anything above 0 USD means a resource outlived its demo: check for a leftover Container Apps
  environment or Cosmos account before touching the budget.
