#############################################
#        Infrastructure & Platform          #
#        Health Report for C Level          #
#############################################

# Create a resource group
resource "azurerm_resource_group" "infrahealth-rg" {
  name     = "rg-infrahealth-ops"
  location = var.region_ne
  tags     = local.tags
}

resource "azurerm_user_assigned_identity" "infrahealth-mi" {
  name                = "mi-infrahealth-ops"
  location            = var.region_ne
  resource_group_name = azurerm_resource_group.infrahealth-rg.name
  tags                = local.tags
}

# Assign KV permissions to Managed ID
resource "azurerm_role_assignment" "infrahealth-mi-kv-perms" {
  scope                = data.azurerm_key_vault.kv-pab-ops-ne.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.infrahealth-mi.principal_id
}

# RBAC — Managed Identity → Log Analytics Reader
resource "azurerm_role_assignment" "infrahealth-mi-law-perms" {
  scope                = local.law_sentinel_id
  role_definition_name = "Log Analytics Reader"
  principal_id         = azurerm_user_assigned_identity.infrahealth-mi.principal_id
}

# App Service Plan — B1 required for VNet integration
resource "azurerm_service_plan" "infrahealth-asp" {
  name                = "asp-infrahealth-ops"
  location            = var.region_ne
  resource_group_name = azurerm_resource_group.infrahealth-rg.name
  os_type             = "Linux"
  sku_name            = "B1"
  tags                = local.tags
}

# App Service
resource "azurerm_linux_web_app" "infrahealth-app" {
  name                            = "app-infrahealth-ops"
  location                        = var.region_ne
  resource_group_name             = azurerm_resource_group.infrahealth-rg.name
  service_plan_id                 = azurerm_service_plan.infrahealth-asp.id
  public_network_access_enabled   = false
  virtual_network_subnet_id       = azurerm_subnet.ops-wapp-subnet.id
  key_vault_reference_identity_id = azurerm_user_assigned_identity.infrahealth-mi.id

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.infrahealth-mi.id]
  }

  site_config {
    always_on              = true
    vnet_route_all_enabled = true
    app_command_line       = "bash startup.sh"
    application_stack {
      python_version = "3.11"
    }
  }
  app_settings = {
    "AZURE_CLIENT_ID" = azurerm_user_assigned_identity.infrahealth-mi.client_id

    "DATADOG_API_KEY" = "@Microsoft.KeyVault(SecretUri=https://${data.azurerm_key_vault.kv-pab-ops-ne.name}.vault.azure.net/secrets/datadog-api-key/)"
    "DATADOG_APP_KEY" = "@Microsoft.KeyVault(SecretUri=https://${data.azurerm_key_vault.kv-pab-ops-ne.name}.vault.azure.net/secrets/datadog-app-key/)"
    "DATADOG_SITE"    = "datadoghq.eu"

    "LOG_ANALYTICS_WORKSPACE_ID" = local.law_sentinel_wsid
    "LA_CLIENT_ID"               = "00000000-0000-0000-0000-000000000000"
    "LA_CLIENT_SECRET"           = "@Microsoft.KeyVault(SecretUri=https://${data.azurerm_key_vault.kv-pab-ops-ne.name}.vault.azure.net/secrets/infrahealth-la-client-secret/)"
    "LA_TENANT_ID"               = "00000000-0000-0000-0000-000000000000"

    "AZURE_SUBSCRIPTION_IDS" = "00000000-0000-0000-0000-000000000001,00000000-0000-0000-0000-000000000002,00000000-0000-0000-0000-000000000003,00000000-0000-0000-0000-000000000004,00000000-0000-0000-0000-000000000005,00000000-0000-0000-0000-000000000006,00000000-0000-0000-0000-000000000007"

    "SCM_DO_BUILD_DURING_DEPLOYMENT" = "true"


  }

  tags = local.tags
}

# Private Endpoint — App Service
resource "azurerm_private_endpoint" "infrahealth-app-pep" {
  name                          = "app-infrahealth-ops-pep"
  location                      = var.region_ne
  resource_group_name           = azurerm_resource_group.infrahealth-rg.name
  custom_network_interface_name = "app-infrahealth-ops-pep-nic"
  subnet_id                     = azurerm_subnet.ops-pep-subnet.id

  private_service_connection {
    name                           = "psc-app-infrahealth-ops"
    private_connection_resource_id = azurerm_linux_web_app.infrahealth-app.id
    subresource_names              = ["sites"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [local.pri_dns_zone_app_id]
  }

  tags = local.tags
}
