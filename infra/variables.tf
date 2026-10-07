variable "subscription_id" {
  description = "Subscription the stack is applied to (az account show --query id)."
  type        = string
}

variable "resource_group" {
  description = "Created once by hand in the bootstrap, because the CI role is scoped to it."
  type        = string
  default     = "rg-dp-staging"
}

variable "name" {
  description = "Prefix for every resource name."
  type        = string
  default     = "dp-staging"
}

variable "image" {
  description = "Initial image; the deploy workflow replaces it on every push to dev."
  type        = string
  default     = "ghcr.io/juandsep/dynamic-pricing-engine:dev"
}

variable "api_key" {
  description = "The key /price and /reward require. Never committed: terraform.tfvars or TF_VAR_api_key."
  type        = string
  sensitive   = true
}

variable "experiment_share" {
  description = "Share of (user, product) pairs priced at random for a price test. 0 serves the policy everywhere."
  type        = number
  default     = 0

  validation {
    condition     = var.experiment_share >= 0 && var.experiment_share <= 1
    error_message = "A share is between 0 and 1."
  }
}

variable "operator_can_read_events" {
  description = "Grant whoever applies read access to Cosmos data, to export the event log for analysis."
  type        = bool
  default     = true
}

variable "cosmos_throughput" {
  description = "Shared by both containers. 1000 RU/s is the free-tier ceiling: above it bills."
  type        = number
  default     = 1000

  validation {
    condition     = var.cosmos_throughput >= 400 && var.cosmos_throughput <= 1000
    error_message = "Above 1000 RU/s the account leaves the free tier and starts billing."
  }
}
