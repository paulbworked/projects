# kpi-dashboard

A private internal web application providing an executive-level Infrastructure and Platform Health Report. Built with Python/Flask, hosted on Azure App Service with private endpoint access only, and deployed via Azure DevOps Pipelines.

## The Problem

Management had no single view of the cloud infrastructure and security posture. Health, reliability and security data was spread across Datadog, Azure Sentinel and Log Analytics — with no way for non-technical stakeholders to understand the state of the environment at a glance, or to track trends month on month.

## What It Does

- Pulls live infrastructure and security metrics from Datadog and Azure Log Analytics / Sentinel
- Displays RAG status (Red / Amber / Green) for all key infrastructure components
- Covers: AKS clusters, MongoDB Atlas shards, PostgreSQL, Service Bus, Virtual Machines, Azure Firewall and security metrics
- Month selector — view current or any previous month
- Executive Summary section with RAG status cards for each area
- Free text notes fields per section for additional context
- Generate Report button for PDF export
- Used by management and C-level to get a clear, consistent view of infrastructure and security health

## How It Was Built

This application was designed and built collaboratively using Claude as an AI pair programmer across multiple sessions. The build covered requirements definition, infrastructure design and Terraform code, Python Flask backend with all Datadog and Log Analytics API integrations, HTML/JS dashboard frontend with RAG status logic, Azure DevOps pipeline YAML, Key Vault secret integration and end-to-end deployment debugging.

It is a real example of how AI can accelerate engineering work — not just generating boilerplate, but working through complex API integrations, authentication patterns and deployment issues iteratively.

## Tech Stack

| Component | Detail |
|-----------|--------|
| Language | Python 3.11 / Flask |
| Data sources | Datadog API (EU), Azure Log Analytics / Sentinel |
| Hosting | Azure App Service (Linux, B1) |
| Inbound access | Private endpoint only — no public access |
| Outbound | VNet Integration |
| Authentication | User-assigned Managed Identity + Key Vault references |
| Secret storage | Azure Key Vault — Datadog API/App keys, LA client secret |
| Infrastructure | Terraform via HCP Terraform Cloud |
| CI/CD | Azure DevOps Pipelines |

## Architecture

The App Service uses a user-assigned Managed Identity with two role assignments:
- **Key Vault Secrets User** — reads Datadog API keys and Log Analytics client secret at runtime via Key Vault references in app settings
- **Log Analytics Reader** — queries the Sentinel workspace directly

All traffic stays on the internal network — no public endpoint.

```
Client (VPN) → Private DNS → App Service Private Endpoint → App Service
                                                                  ↓
                                              VNet Integration → Datadog API (EU)
                                                                  ↓
                                              VNet Integration → Log Analytics / Sentinel
                                                                  ↓
                                              Key Vault Reference → API Keys at runtime
```

## Repository Structure

```
kpi-dashboard/
├── app/
│   ├── app.py               # Flask backend — all API endpoints for Datadog and Log Analytics
│   ├── dashboard.html       # Frontend dashboard — RAG status, metrics, month selector, notes
│   ├── requirements.txt     # Python dependencies (flask, datadog-api-client)
│   └── startup.sh           # App Service startup command
├── terraform/
│   └── infrahealth.tf       # Azure infrastructure — resource group, user-assigned managed identity,
│                            # RBAC assignments, App Service plan, web app, private endpoint
└── yaml/
    └── Infra-Health.yml     # Azure DevOps pipeline — zip and deploy to App Service
```

## API Endpoints

The Flask backend exposes dedicated endpoints for each infrastructure component, all accepting a `?month_offset=0` parameter (0 = current month, -1 = previous month):

| Endpoint | Data Source | Metrics |
|----------|-------------|---------|
| `/api/aks` | Datadog | Node availability, pod status, restart counts |
| `/api/mongodb` | Datadog | Per-shard availability, connections, query latency |
| `/api/postgres` | Datadog | Availability, CPU, connections, replication lag |
| `/api/servicebus` | Datadog | Incoming/outgoing messages, dead letter counts |
| `/api/virtualmachines` | Datadog | VM availability, CPU, disk read |
| `/api/security` | Log Analytics / Sentinel | Security incidents, alerts by severity |
| `/health` | — | Health check endpoint |

## Infrastructure (terraform/)

The Terraform code provisions all Azure resources:

- Resource group
- User-assigned Managed Identity with Key Vault Secrets User and Log Analytics Reader role assignments
- App Service Plan (Linux, B1) and Web App (Python 3.11, VNet integrated)
- Key Vault references in app settings for Datadog API/App keys and Log Analytics client secret — secrets are never stored in code or plain text settings
- Private endpoint for App Service with DNS zone group
- `public_network_access_enabled = false` — no public access

The user-assigned identity approach (rather than system-assigned) was chosen to allow the identity to be pre-created and granted Key Vault permissions before the App Service is deployed, avoiding a chicken-and-egg dependency.

## Pipeline (yaml/)

The Azure DevOps pipeline (`Infra-Health.yml`) runs on a self-hosted Linux agent scale set. It:

1. Zips the application code
2. Deploys to the App Service via the `AzureWebApp@1` task

The pipeline is manually triggered — `trigger: enabled: false`.

## Author

Paul Boardman — [linkedin.com/in/paulboardman76](https://linkedin.com/in/paulboardman76)
