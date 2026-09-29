# Infrastructure — Dynamic Pricing Engine (Azure)

Terraform (`azurerm`) provisioning the resources the service needs:

| Resource | Purpose |
|---|---|
| Azure Container Registry | image storage for the priced service |
| Container Apps Environment + App | runtime, ingress and revisions |
| Azure Cache for Redis | online feature store (posterior + hot features) |
| Azure Cosmos DB (NoSQL, serverless) | served arms, rewards and attributes |
| Azure Key Vault | secrets, read through a managed identity |
| Log Analytics + Application Insights | logs, metrics and traces |

## Layout

```
infra/
├─ main.tf                    # provider, resource group and wiring
├─ variables.tf               # inputs (region, names, SKUs)
├─ outputs.tf                 # endpoint and registry names for CI
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

`terraform.tfvars` is git-ignored. Keep one workspace per environment
(`staging`, `production`) and never reuse the production state locally.

## Conventions

- One module per resource group concern; the reference layout lives in
  `portfolio-infra`.
- No credentials in state: Key Vault holds secrets and workloads authenticate
  with managed identities.
- CI authenticates to Azure through OIDC federated credentials, not stored keys.
