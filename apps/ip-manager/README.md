# ip-manager

A private internal web application for managing and tracking Azure and AWS network address space allocation. Built with Python/Flask, hosted on Azure App Service with private endpoint access only, and deployed via Azure DevOps Pipelines.

## The Problem

As the cloud estate grew across multiple Azure environments and AWS accounts — each with their own VNets, subnets, VPN gateways and firewall IPs — tracking what address space was allocated, free or reserved became unmanageable manually. There was no single source of truth for IP allocation across the estate.

## What It Does

- Manages network address space allocation rooted at `10.0.0.0/8`
- Tracks Virtual Networks, vWAN hubs, VPN Gateways and subnets with assigned CIDRs
- Visually highlights free subnets available for allocation
- Allocates individual IP addresses to named services within subnets
- Tracks external firewall IPs as a reference table
- Accessible only from inside the private network — no public internet access

## How It Was Built

This application was designed and built collaboratively using Claude as an AI pair programmer. The full build covered requirements definition, architecture design, infrastructure Terraform code, Flask application code (models, routes, templates), Azure DevOps pipeline YAML, database migrations and debugging end-to-end deployment issues — including Managed Identity SQL grants, private endpoint DNS resolution and App Service startup configuration.

It is a real example of how AI can be used as a practical engineering tool — not just generating boilerplate, but working through real deployment problems iteratively.

## Tech Stack

| Component | Detail |
|-----------|--------|
| Language | Python 3.12 / Flask |
| Database | Azure SQL (Basic tier) |
| ORM | SQLAlchemy + Flask-Migrate |
| Hosting | Azure App Service (Linux, B1) |
| Inbound access | Private endpoint only — no public access |
| Outbound | VNet Integration |
| DB authentication | Managed Identity — no stored credentials |
| Infrastructure | Terraform via HCP Terraform Cloud |
| CI/CD | Azure DevOps Pipelines |

## Architecture

All traffic stays on the internal network. The App Service has no public endpoint — clients on the VNet (or connected via VPN) resolve the app hostname via a Private DNS Zone pointing to the private endpoint NIC. The App Service uses VNet Integration to route all outbound traffic, including calls to Azure SQL, back through the VNet.

```
Client (VPN) → Private DNS → App Service Private Endpoint → App Service
                                                                  ↓
                                                    VNet Integration
                                                                  ↓
                                              SQL Private Endpoint → Azure SQL
```

## Repository Structure

```
ip-manager/
├── app/
│   ├── __init__.py          # App factory — Flask, SQLAlchemy, blueprints
│   ├── config.py            # Config — reads env vars, builds Managed Identity connection string
│   ├── models.py            # SQLAlchemy data models
│   ├── routes/
│   │   ├── __init__.py
│   │   └── main.py          # All Flask URL routes and form handling
│   └── templates/           # Jinja2 HTML templates
│       ├── base.html        # Master layout with navigation
│       ├── index.html       # Main dashboard
│       ├── free_space.html  # Free subnet viewer
│       ├── settings.html    # Application settings
│       ├── add_*.html       # Add forms (address space, VNet, subnet, IP, firewall IP)
│       └── edit_*.html      # Edit forms (subnet, address space)
├── run.py                   # Entry point for gunicorn
├── requirements.txt         # Python dependencies
├── startup.sh               # App Service startup command
├── terraform/
│   └── ipman.tf             # Azure infrastructure — resource group, SQL server, SQL database,
│                            # App Service plan, web app, private endpoints for SQL and App Service
└── yaml/
    └── IP-Manager.yml       # Azure DevOps pipeline — build and deploy to App Service
```

## Data Models

| Model | Key Fields |
|-------|------------|
| `AddressSpace` | id, cidr, name, description |
| `VirtualNetwork` | id, name, cidr, region, resource_group, env, type (VNet/vWAN/VPN), address_space_id |
| `Subnet` | id, name, cidr, purpose, status (free/reserved/assigned), allocated_to, vnet_id |
| `IPAddress` | id, address, service_name, description, subnet_id, allocated_at |
| `FirewallExternalIP` | id, public_ip, label, mapped_to_service, firewall_rule_ref, notes |

## Infrastructure (terraform/)

The Terraform code provisions all Azure resources required to run the application:

- Resource group
- Azure SQL Server (Entra AD authentication only, public access disabled) and SQL Database (Basic tier)
- Private endpoint for SQL with DNS zone group
- App Service Plan (Linux, B1) and Web App (Python 3.12, VNet integrated, system-assigned Managed Identity)
- Private endpoint for App Service with DNS zone group
- App settings injected at infrastructure level — SQL server FQDN and database name passed to Flask at runtime

SQL admin credentials are sourced from Key Vault secrets. The Managed Identity is used at runtime for passwordless SQL authentication — no credentials are stored in application code or settings.

## Pipeline (yaml/)

The Azure DevOps pipeline (`IP-Manager.yml`) runs on a self-hosted Linux agent scale set. It:

1. Installs Python dependencies into a virtual environment
2. Zips the application code
3. Deploys to the App Service via the `AzureWebApp@1` task

The pipeline is manually triggered — `trigger: enabled: false`.

## Author

Paul Boardman — [linkedin.com/in/paulboardman76](https://linkedin.com/in/paulboardman76)

