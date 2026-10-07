data "azurerm_resource_group" "this" {
  name = var.resource_group
}

data "azurerm_client_config" "current" {}

locals {
  location = data.azurerm_resource_group.this.location
  # Cosmos names are global; a hash of the subscription keeps them unique without
  # a random provider and stable across destroy/apply.
  suffix = substr(sha1(data.azurerm_client_config.current.subscription_id), 0, 6)
}

# --- Cosmos DB: posteriors and events ---------------------------------------

resource "azurerm_cosmosdb_account" "this" {
  name                = "${var.name}-${local.suffix}"
  resource_group_name = data.azurerm_resource_group.this.name
  location            = local.location
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"

  # One free-tier account per subscription, and the opt-in only exists at creation.
  free_tier_enabled = true
  # Keys off: the only way in is Entra ID (the app's managed identity).
  local_authentication_enabled = false

  consistency_policy {
    consistency_level = "Session"
  }

  geo_location {
    location          = local.location
    failover_priority = 0
  }
}

resource "azurerm_cosmosdb_sql_database" "pricing" {
  name                = "pricing"
  resource_group_name = data.azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.this.name
  # Database-level throughput, shared by both containers: one free 1000 RU/s pool
  # instead of 400 RU/s per container.
  throughput = var.cosmos_throughput
}

resource "azurerm_cosmosdb_sql_container" "this" {
  for_each = toset(["posteriors", "events"])

  name                  = each.key
  resource_group_name   = data.azurerm_resource_group.this.name
  account_name          = azurerm_cosmosdb_account.this.name
  database_name         = azurerm_cosmosdb_sql_database.pricing.name
  partition_key_paths   = ["/id"]
  partition_key_version = 2
}

# --- Container Apps: the API -------------------------------------------------

# No Log Analytics workspace: logs stream with `az containerapp logs show` during a
# demo, and nothing is ingested or retained between demos.
resource "azurerm_container_app_environment" "this" {
  name                = var.name
  resource_group_name = data.azurerm_resource_group.this.name
  location            = local.location
}

resource "azurerm_container_app" "api" {
  name                         = "${var.name}-api"
  resource_group_name          = data.azurerm_resource_group.this.name
  container_app_environment_id = azurerm_container_app_environment.this.id
  revision_mode                = "Single"

  identity {
    type = "SystemAssigned"
  }

  secret {
    name  = "api-key"
    value = var.api_key
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    # Scale to zero: an idle revision bills nothing. One replica at most, because the
    # rate limit is per replica and the posterior has a single writer path
    # (docs/architecture.md).
    min_replicas = 0
    max_replicas = 1

    container {
      name   = "api"
      image  = var.image
      cpu    = 0.25
      memory = "0.5Gi"

      env {
        name  = "COSMOS_ENDPOINT"
        value = azurerm_cosmosdb_account.this.endpoint
      }
      env {
        name  = "EXPERIMENT_SHARE"
        value = tostring(var.experiment_share)
      }
      env {
        name        = "API_KEY"
        secret_name = "api-key" # pragma: allowlist secret
      }

      liveness_probe {
        transport = "HTTP"
        port      = 8000
        path      = "/health"
      }
      readiness_probe {
        transport = "HTTP"
        port      = 8000
        path      = "/ready"
      }
    }
  }

  lifecycle {
    # The deploy workflow owns the image tag; Terraform owns everything else.
    ignore_changes = [template[0].container[0].image]
  }
}

# Data-plane access for the app's identity: Cosmos DB Built-in Data Contributor.
resource "azurerm_cosmosdb_sql_role_assignment" "api" {
  resource_group_name = data.azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.this.name
  role_definition_id  = "${azurerm_cosmosdb_account.this.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id        = azurerm_container_app.api.identity[0].principal_id
  scope               = azurerm_cosmosdb_account.this.id
}

# Read-only data access for the person who applies the stack (their Azure CLI login),
# so `python -m dp.export` can read the event log with local keys disabled.
resource "azurerm_cosmosdb_sql_role_assignment" "operator" {
  count               = var.operator_can_read_events ? 1 : 0
  resource_group_name = data.azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.this.name
  role_definition_id  = "${azurerm_cosmosdb_account.this.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000001"
  principal_id        = data.azurerm_client_config.current.object_id
  scope               = azurerm_cosmosdb_account.this.id
}
