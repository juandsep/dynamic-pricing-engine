terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
  # State lives in the portfolio's shared GCS state bucket, not in an Azure storage
  # account: that account would be the one resource nobody ever destroys, while the
  # bucket already exists and costs nothing. `terraform init` needs Google
  # application-default credentials.
  backend "gcs" {
    bucket = "jd-portfolio-shared-tfstate"
    prefix = "dynamic-pricing-engine"
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}
