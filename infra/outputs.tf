output "url" {
  value = "https://${azurerm_container_app.api.ingress[0].fqdn}"
}

output "container_app" {
  description = "Name the deploy workflow passes to az containerapp update."
  value       = azurerm_container_app.api.name
}

output "cosmos_endpoint" {
  value = azurerm_cosmosdb_account.this.endpoint
}
