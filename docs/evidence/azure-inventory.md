# Azure staging inventory

Captured 2026-10-05 05:22 UTC with the Azure CLI, before `terraform destroy`. Identifiers of the subscription and tenant are omitted.

## Resources in `rg-dp-staging`

```text
Name               Location
-----------------  ----------
dp-staging         eastus2
dp-staging-6f6cab  eastus2
dp-staging-api     eastus2
```

## Container App

```text
cpu: 0.25
identity: SystemAssigned
image: ghcr.io/juandsep/dynamic-pricing-engine:ff0a389d86ad96f23ec028d2c42632c7cf037aff
ingressPort: 8000
maxReplicas: 1
memory: 0.5Gi
minReplicas: null        # unset is the platform default: 0, scale to zero
probes:
- Liveness
- Readiness
revision: dp-staging-api--0000003
secrets:
- api-key
```

## Cosmos DB account

```text
consistency: Session
freeTier: true
localAuthDisabled: true
locations:
- East US 2

databaseThroughputRUs: 1000
Container    PartitionKey
-----------  --------------
events       /id
posteriors   /id
```

## The app's data-plane role on Cosmos

```text
sqlRoleDefinition 00000000-0000-0000-0000-000000000002 (Cosmos DB Built-in Data Contributor)
```

## GitHub Actions identity (OIDC)

```text
Name                        Subject
--------------------------  ----------------------------------------------------------------------------
github-environment-staging  repo:juandsep@30062465/dynamic-pricing-engine@1396685418:environment:staging
github-dev                  repo:juandsep@30062465/dynamic-pricing-engine@1396685418:ref:refs/heads/dev
Contributor	/subscriptions/<sub>/resourceGroups/rg-dp-staging
```
