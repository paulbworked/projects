#############################################
#          IP Manager Application           #
#   Used to keep track of address spaces    #
#############################################

# Create a resource group
resource "azurerm_resource_group" "ipman-rg" {
  name     = "rg-ipman-ops"
  location = var.region_ne

  tags = local.tags
}

##################################################
# Create Azure SQL Instance and Private Endpoint #
##################################################

# Create MS SQL Server
resource "azurerm_mssql_server" "ipman-sql" {
  name                          = "sql-ipmanager-ops"
  resource_group_name           = azurerm_resource_group.ipman-rg.name
  location                      = var.region_ne
  version                       = "12.0"
  administrator_login           = azurerm_key_vault_secret.ipman-sqladmin-log.value
  administrator_login_password  = azurerm_key_vault_secret.ipman-sqladmin-pass.value
  minimum_tls_version           = "1.2"
  public_network_access_enabled = false

  azuread_administrator {
    login_username = data.azuread_group.cloudops.display_name
    object_id      = data.azuread_group.cloudops.object_id
    tenant_id      = local.tenant_id
  }

  tags = local.tags

}

# Creating MS SQL Database
resource "azurerm_mssql_database" "ipman-sqldb" {
  name      = "sqldb-ipmanager-ops"
  server_id = azurerm_mssql_server.ipman-sql.id
  sku_name  = "Basic"

  tags = local.tags

}

# Create PEP for MS SQL Database
resource "azurerm_private_endpoint" "ipman-sql-pep" {
  name                          = "sql-ipmanager-ops-pep"
  location                      = var.region_ne
  resource_group_name           = azurerm_resource_group.ipman-rg.name
  subnet_id                     = azurerm_subnet.ops-pep-subnet.id
  custom_network_interface_name = "sql-ipmanager-ops-pep-nic"

  private_service_connection {
    name                           = "psc-sql-ipmanager"
    private_connection_resource_id = azurerm_mssql_server.ipman-sql.id
    subresource_names              = ["sqlServer"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [local.pri_dns_zone_sql_id]
  }
  tags = local.tags
}

###########################################
# Create App Service and Private Endpoint #
###########################################

# Create App Service Plan
resource "azurerm_service_plan" "ipman-asp" {
  name                = "asp-ipmanager-ops"
  location            = var.region_ne
  resource_group_name = azurerm_resource_group.ipman-rg.name
  os_type             = "Linux"
  sku_name            = "B1"

  tags = local.tags

}

# Create web app
resource "azurerm_linux_web_app" "ipman-app" {
  name                          = "app-ipmanager-ops"
  location                      = var.region_ne
  resource_group_name           = azurerm_resource_group.ipman-rg.name
  service_plan_id               = azurerm_service_plan.ipman-asp.id
  public_network_access_enabled = false
  virtual_network_subnet_id     = azurerm_subnet.ops-wapp-subnet.id

  identity {
    type = "SystemAssigned"
  }

  site_config {
    always_on              = true
    vnet_route_all_enabled = true
    app_command_line       = "bash startup.sh"
    application_stack {
      python_version = "3.12"
    }
  }

  app_settings = {
    "AZURE_SQL_SERVER"               = azurerm_mssql_server.ipman-sql.fully_qualified_domain_name
    "AZURE_SQL_DATABASE"             = azurerm_mssql_database.ipman-sqldb.name
    "FLASK_ENV"                      = "production"
    "SCM_DO_BUILD_DURING_DEPLOYMENT" = "true"
  }

  tags = local.tags

}

# Create PEP for app
resource "azurerm_private_endpoint" "ipman-app-pep" {
  name                          = "app-ipmanager-ops-pep"
  location                      = var.region_ne
  resource_group_name           = azurerm_resource_group.ipman-rg.name
  subnet_id                     = azurerm_subnet.ops-pep-subnet.id
  custom_network_interface_name = "app-ipmanager-ops-pep-nic"

  private_service_connection {
    name                           = "psc-app-ipmanager"
    private_connection_resource_id = azurerm_linux_web_app.ipman-app.id
    subresource_names              = ["sites"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [local.pri_dns_zone_app_id]
  }
  tags = local.tags
}
