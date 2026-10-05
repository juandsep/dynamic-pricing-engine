terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
  # State stays local on purpose (infra/*.tfstate is git-ignored): a state storage
  # account would be the one resource nobody ever destroys.
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}
