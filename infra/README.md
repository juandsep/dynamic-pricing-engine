# Infrastructure — Dynamic Pricing Engine (Azure)

Terraform (`azurerm`) provisioning the resources the service needs. Every resource here is free-tier
or inside a per-subscription free grant: the running bill is **0 USD/month** and there is no fixed
line item. The prices behind the rejections below come from the Azure retail prices API.

| Resource | Purpose | Cost |
|---|---|---|
| Container Apps Environment + App | runtime, ingress and revisions; min 0 replicas | 0 — inside the monthly free grant (180,000 vCPU-s, 360,000 GiB-s, 2M requests per subscription) |
| Azure Cosmos DB (NoSQL, **provisioned 1000 RU/s**, free tier enabled at creation) | posterior, served arms, rewards and attributes | 0 — free tier covers the first 1000 RU/s and 25 GB for the lifetime of the account, one account per subscription |
| Managed identity + Cosmos data-plane role assignment | lets the app read and write Cosmos with no connection string | 0 |
| Log Analytics + Application Insights (optional) | logs, metrics and traces | 0 at demo volume — set the environment's log destination to `none` to skip it entirely |

Deliberately **not** provisioned, and why:

| Rejected | Would cost | Replacement |
|---|---|---|
| Azure Cache for Redis (Basic C0) | ~20 USD/month, fixed | the posterior document in Cosmos DB (one replica; see `docs/architecture.md`) |
| Azure Container Registry (Basic) | ~5.03 USD/month, billed even with nothing deployed | GHCR public package, pulled anonymously |
| Azure Key Vault | ~0, but a service and a code path | managed identity to Cosmos, OIDC in CI; no secret exists to store |
| MLflow on Container Apps + Azure Files/PostgreSQL | ~15-20 USD/month, fixed | MLflow hosted free on DagsHub |
| Cosmos DB **serverless** | per-RU billing | provisioned 1000 RU/s — free tier does not apply to serverless accounts |

## Layout

```
infra/
├─ main.tf                    # provider, resource group and wiring
├─ variables.tf               # inputs (region, names, throughput)
├─ outputs.tf                 # endpoint and role assignment for CI
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

`terraform.tfvars` is git-ignored. Keep one workspace per environment (`staging`, `production`) and
never reuse the production state locally.

**Ephemeral by design.** Resources are applied before a demo or a screenshot session and destroyed
afterwards:

```bash
terraform destroy -var-file=terraform.tfvars
```

Free grants cover the running hours; destroying removes the ones that bill while idle. Terraform
state stays local (`infra/*.tfstate` is git-ignored) because a state storage account would be the
only resource nobody ever destroys.

## Conventions

- One module per resource group concern. The layout in this repository is the reference for Azure;
  `portfolio-infra` is GCP-only (`google` providers) and must not be mirrored here.
- No secrets in state — and no secrets at all. Workloads authenticate with managed identities and
  data-plane role assignments; CI authenticates to Azure through OIDC federated credentials.
- Region: `eastus2`. Container Apps bills 2.4e-05 USD per vCPU-second and 3e-06 per GiB-second there;
  `spaincentral` and `westeurope` bill 3.4e-05 and 4e-06, about 42 % more on the same workload.
- Cosmos throughput is fixed at 1000 RU/s (the free-tier ceiling). A burst above it returns 429s;
  the upgrade path is autoscale, then serverless — both of which start billing.
- **Budget: fixed at 10 USD/month** for the subscription, with notifications at 50 %, 90 % and 100 %.
  It is a tripwire, not a hard stop — an Azure budget only alerts. It is configured with the CLI and
  not by Terraform, because it is an account-level guard rather than a resource of this stack.
  Anything above 0 USD means a resource outlived its demo: check for a leftover Container Apps
  environment or Cosmos account before touching the budget.
