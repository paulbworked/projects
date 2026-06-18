import os
import io
import json
import requests
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory, send_file
from datetime import datetime, timezone

app = Flask(__name__)

def get_month_range(month_offset=0):
    now = datetime.now(timezone.utc)
    month = now.month + month_offset
    year = now.year

    if month <= 0:
        month += 12
        year -= 1

    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)

    return int(start.timestamp()), int(end.timestamp())


def query_metric(metric, filter_tag, start, end, aggregation="avg"):
    api_key = os.environ.get("DATADOG_API_KEY")
    app_key = os.environ.get("DATADOG_APP_KEY")
    site = os.environ.get("DATADOG_SITE", "datadoghq.eu")

    query = f"{aggregation}:{metric}{{{filter_tag}}}"

    response = requests.get(
        f"https://api.{site}/api/v1/query",
        headers={
            "DD-API-KEY": api_key,
            "DD-APPLICATION-KEY": app_key,
        },
        params={
            "query": query,
            "from": start,
            "to": end,
        }
    )

    data = response.json()

    if data.get("status") != "ok":
        return None

    series = data.get("series", [])
    if not series:
        return None

    pointlist = series[0].get("pointlist", [])
    if not pointlist:
        return None

    values = [p[1] for p in pointlist if p[1] is not None]
    return values if values else None


def avg(values):
    return round(sum(values) / len(values), 2) if values else None

def latest(values):
    return round(values[-1], 2) if values else None

def total(values):
    return round(sum(values), 2) if values else None


# ─── Log Analytics ──────────────────────────────────────────

def get_managed_identity_token():
    tenant_id = os.environ.get("LA_TENANT_ID")
    client_id = os.environ.get("LA_CLIENT_ID")
    client_secret = os.environ.get("LA_CLIENT_SECRET")

    response = requests.post(
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "resource": "https://api.loganalytics.io"
        }
    )
    return response.json().get("access_token")


def query_log_analytics(query, timespan="P30D"):
    workspace_id = os.environ.get("LOG_ANALYTICS_WORKSPACE_ID")
    token = get_managed_identity_token()

    response = requests.post(
        f"https://api.loganalytics.io/v1/workspaces/{workspace_id}/query",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        json={
            "query": query,
            "timespan": timespan
        }
    )

    data = response.json()
    tables = data.get("tables", [])
    if not tables:
        return []

    columns = [col["name"] for col in tables[0]["columns"]]
    rows = tables[0]["rows"]
    return [dict(zip(columns, row)) for row in rows]


# ─── Resource Graph ─────────────────────────────────────────

def get_arm_token():
    tenant_id = os.environ.get("LA_TENANT_ID")
    client_id = os.environ.get("LA_CLIENT_ID")
    client_secret = os.environ.get("LA_CLIENT_SECRET")

    response = requests.post(
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "resource": "https://management.azure.com"
        }
    )
    return response.json().get("access_token")


def query_resource_graph(query):
    token = get_arm_token()
    subscriptions = os.environ.get("AZURE_SUBSCRIPTION_IDS", "").split(",")

    response = requests.post(
        "https://management.azure.com/providers/Microsoft.ResourceGraph/resources?api-version=2021-03-01",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        json={
            "subscriptions": subscriptions,
            "query": query
        }
    )

    data = response.json()
    return data.get("data", [])


# ─── Notes ──────────────────────────────────────────────────

NOTES_DIR = Path("/home/data/notes")

def get_notes_key(section, month_offset):
    now = datetime.now(timezone.utc)
    month = now.month + month_offset
    year = now.year
    if month <= 0:
        month += 12
        year -= 1
    return f"{year}-{month:02d}"


def read_notes(section, month_offset):
    key = get_notes_key(section, month_offset)
    filepath = NOTES_DIR / f"{section}_{key}.json"
    if filepath.exists():
        return json.loads(filepath.read_text())
    return {"section": section, "month": key, "content": ""}


def write_notes(section, month_offset, content):
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    key = get_notes_key(section, month_offset)
    filepath = NOTES_DIR / f"{section}_{key}.json"
    data = {"section": section, "month": key, "content": content}
    filepath.write_text(json.dumps(data))
    return data


NOTES_SECTIONS = [
    "security",
    "reliability",
    "vulnerability",
    "upcoming-scheduled-maintenance",
    "upcoming-operational-tasks",
    "upcoming-projects"
]


# ─── MongoDB ────────────────────────────────────────────────

@app.route("/api/mongodb")
def mongodb():
    month_offset = int(request.args.get("month_offset", 0))
    start, end = get_month_range(month_offset)

    shards = [
        "hostnameport:pab-prod-shard-00-00.example.mongodb.net:27017",
        "hostnameport:pab-prod-shard-00-01.example.mongodb.net:27017",
        "hostnameport:pab-prod-shard-00-02.example.mongodb.net:27017",
    ]

    results = {}
    for shard in shards:
        shard_name = shard.split(":")[1].split(".")[0]

        connections = query_metric("mongodb.atlas.connections.current", shard, start, end)
        disk_used = query_metric("mongodb.atlas.system.disk.space.used", shard, start, end)
        disk_iops = query_metric("mongodb.atlas.system.disk.iops.total", shard, start, end)
        repl_health = query_metric("mongodb.atlas.replstatus.health", shard, start, end)
        repl_lag = query_metric("mongodb.atlas.replset.replicationlag", shard, start, end)

        results[shard_name] = {
            "connections_avg": avg(connections),
            "disk_used_latest_gb": round(latest(disk_used) / 1e9, 2) if latest(disk_used) else None,
            "disk_iops_avg": avg(disk_iops),
            "replication_health": latest(repl_health),
            "replication_lag_avg_seconds": avg(repl_lag),
        }

    return jsonify({"month_offset": month_offset, "mongodb": results})


# ─── PostgreSQL ─────────────────────────────────────────────

@app.route("/api/postgresql")
def postgresql():
    month_offset = int(request.args.get("month_offset", 0))
    start, end = get_month_range(month_offset)

    tag = "name:psql-pab-prod-ne"

    connections = query_metric("azure.dbforpostgresql_flexibleservers.active_connections", tag, start, end)
    storage = query_metric("azure.dbforpostgresql_flexibleservers.storage_used", tag, start, end)

    return jsonify({
        "month_offset": month_offset,
        "postgresql": {
            "connections_avg": avg(connections),
            "storage_used_latest_gb": round(latest(storage) / 1e9, 2) if latest(storage) else None,
        }
    })


# ─── Kubernetes ─────────────────────────────────────────────

@app.route("/api/kubernetes")
def kubernetes():
    month_offset = int(request.args.get("month_offset", 0))
    start, end = get_month_range(month_offset)

    tag = "kube_cluster_name:aks-pab-prod-ne"

    container_restarts = query_metric("kubernetes.containers.restarts", tag, start, end)
    node_count = query_metric("kubernetes_state.node.count", tag, start, end)
    node_status = query_metric("kubernetes_state.node.status", tag, start, end)
    pod_status = query_metric("kubernetes_state.pod.status_phase", tag, start, end)
    terminated = query_metric("kubernetes_state.container.status_report.count.terminated", tag, start, end)
    waiting = query_metric("kubernetes_state.container.status_report.count.waiting", tag, start, end)

    return jsonify({
        "month_offset": month_offset,
        "kubernetes": {
            "container_restarts_total": total(container_restarts),
            "node_count_latest": latest(node_count),
            "node_status_avg": avg(node_status),
            "pod_status_avg": avg(pod_status),
            "containers_terminated_total": total(terminated),
            "containers_waiting_total": total(waiting),
        }
    })


# ─── Service Bus ────────────────────────────────────────────

@app.route("/api/servicebus")
def servicebus():
    month_offset = int(request.args.get("month_offset", 0))
    start, end = get_month_range(month_offset)

    tag = "name:sbns-pab-prod-ne"

    incoming = query_metric("azure.servicebus_namespaces.incoming_messages", tag, start, end, aggregation="sum")
    outgoing = query_metric("azure.servicebus_namespaces.outgoing_messages", tag, start, end, aggregation="sum")
    dead_letter = query_metric("azure.servicebus_namespaces.count_of_dead_lettered_messages_in_a_queue", tag, start, end)

    return jsonify({
        "month_offset": month_offset,
        "servicebus": {
            "incoming_messages_total": total(incoming),
            "outgoing_messages_total": total(outgoing),
            "dead_lettered_messages_avg": avg(dead_letter),
        }
    })


# ─── Virtual Machines ───────────────────────────────────────

@app.route("/api/virtualmachines")
def virtualmachines():
    month_offset = int(request.args.get("month_offset", 0))
    start, end = get_month_range(month_offset)

    tag = "host:vmopraprodne"

    availability = query_metric("azure.vm.vm_availability_metric_preview", tag, start, end)
    cpu = query_metric("azure.vm.percentage_cpu", tag, start, end)
    disk_read = query_metric("azure.vm.os_disk_read_bytes_sec", tag, start, end)

    return jsonify({
        "month_offset": month_offset,
        "virtual_machines": {
            "availability_avg_percent": round(avg(availability) * 100, 2) if avg(availability) else None,
            "cpu_avg_percent": avg(cpu),
            "disk_read_avg_bytes_sec": avg(disk_read),
        }
    })


# ─── Security ───────────────────────────────────────────────

@app.route("/api/security")
def security():
    month_offset = int(request.args.get("month_offset", 0))
    start, end = get_month_range(month_offset)

    start_dt = datetime.fromtimestamp(start, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_dt = datetime.fromtimestamp(end, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    timespan = f"{start_dt}/{end_dt}"

    threat_intel = query_log_analytics("""
        AZFWThreatIntel
        | summarize total_hits = count() by Action
    """, timespan)

    top_threat_ips = query_log_analytics("""
        AZFWThreatIntel
        | summarize count_ = count() by SourceIp
        | top 10 by count_
    """, timespan)

    top_denied_ips = query_log_analytics("""
        AZFWNetworkRule
        | where Action == "Deny"
        | summarize count_ = count() by SourceIp
        | top 10 by count_
    """, timespan)

    incidents = query_log_analytics("""
        SecurityIncident
        | summarize count() by Severity
    """, timespan)

    alerts = query_log_analytics("""
        SecurityAlert
        | summarize count() by AlertSeverity
    """, timespan)

    return jsonify({
        "month_offset": month_offset,
        "security": {
            "threat_intel_hits": threat_intel,
            "top_threat_intel_ips": top_threat_ips,
            "top_denied_ips": top_denied_ips,
            "incidents_by_severity": incidents,
            "alerts_by_severity": alerts,
        }
    })


# ─── Patching ───────────────────────────────────────────────

@app.route("/api/patching")
def patching():
    month_offset = int(request.args.get("month_offset", 0))
    start, end = get_month_range(month_offset)

    start_dt = datetime.fromtimestamp(start, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_dt = datetime.fromtimestamp(end, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    compliance = query_resource_graph("""
        patchassessmentresources
        | where type =~ "microsoft.compute/virtualmachines/patchassessmentresults"
        | extend properties = parse_json(properties)
        | extend critical = toint(properties.availablePatchCountByClassification.critical)
        | extend security = toint(properties.availablePatchCountByClassification.security)
        | parse id with * 'achines/' resourceName '/patchAssessmentResults/' *
        | extend compliant = iff(critical == 0 and security == 0, true, false)
        | summarize totalVMs = count(), compliantVMs = countif(compliant == true)
        | extend compliancePercent = round(100.0 * compliantVMs / totalVMs, 1)
    """)

    non_compliant = query_resource_graph("""
        patchassessmentresources
        | where type =~ "microsoft.compute/virtualmachines/patchassessmentresults"
        | extend properties = parse_json(properties)
        | extend critical = toint(properties.availablePatchCountByClassification.critical)
        | extend security = toint(properties.availablePatchCountByClassification.security)
        | parse id with * 'achines/' resourceName '/patchAssessmentResults/' *
        | where critical > 0 or security > 0
        | project resourceName, critical, security
        | order by critical desc
    """)

    patches_applied = query_resource_graph(f"""
        patchinstallationresources
        | where type =~ "microsoft.compute/virtualmachines/patchinstallationresults"
        | where properties.lastModifiedDateTime >= datetime({start_dt}) and properties.lastModifiedDateTime < datetime({end_dt})
        | extend installedPatches = toint(properties.installedPatchCount)
        | parse id with * 'achines/' resourceName '/patchInstallationResults/' *
        | summarize totalInstalled = sum(installedPatches)
    """)

    return jsonify({
        "month_offset": month_offset,
        "patching": {
            "compliance_summary": compliance[0] if compliance else {},
            "non_compliant_vms": non_compliant,
            "patches_applied_this_month": patches_applied[0] if patches_applied else {"totalInstalled": 0}
        }
    })


# ─── Cloudflare ─────────────────────────────────────────────

@app.route("/api/cloudflare")
def cloudflare():
    month_offset = int(request.args.get("month_offset", 0))
    start, end = get_month_range(month_offset)

    total_threats = query_metric("cloudflare.threats.all", "*", start, end, aggregation="sum")

    threat_countries = []
    country_codes = ["us", "cn", "ru", "de", "gb", "fr", "nl", "br", "in", "jp", "ua", "kr", "ca", "au", "it"]
    for country in country_codes:
        values = query_metric("cloudflare.threats.country", f"country:{country}", start, end, aggregation="sum")
        if values:
            threat_countries.append({
                "country": country.upper(),
                "threats": total(values)
            })
    threat_countries = sorted(threat_countries, key=lambda x: x["threats"] or 0, reverse=True)[:10]

    badhost = query_metric("cloudflare.requests.ip_class", "ip_class:badhost", start, end, aggregation="sum")
    tor = query_metric("cloudflare.requests.ip_class", "ip_class:tor", start, end, aggregation="sum")

    return jsonify({
        "month_offset": month_offset,
        "cloudflare": {
            "total_threats": total(total_threats),
            "top_threat_countries": threat_countries,
            "bot_traffic": {
                "badhost": total(badhost),
                "tor": total(tor)
            }
        }
    })


# ─── Notes ──────────────────────────────────────────────────

@app.route("/api/notes/<section>", methods=["GET", "POST"])
def notes(section):
    if section not in NOTES_SECTIONS:
        return jsonify({"error": "Invalid section"}), 404

    month_offset = int(request.args.get("month_offset", 0))

    if request.method == "GET":
        return jsonify(read_notes(section, month_offset))

    data = request.get_json()
    if not data or "content" not in data:
        return jsonify({"error": "content field required"}), 400

    return jsonify(write_notes(section, month_offset, data["content"]))


# ─── PDF Report ─────────────────────────────────────────────

def rag_label(status):
    return {"green": "GREEN", "amber": "AMBER", "red": "RED"}.get(status, "—")

@app.route("/api/report")
def generate_report():
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, PageBreak
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

    month_offset = int(request.args.get("month_offset", 0))

    # Fetch all data by calling internal functions directly
    start, end = get_month_range(month_offset)
    start_dt = datetime.fromtimestamp(start, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_dt = datetime.fromtimestamp(end, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    timespan = f"{start_dt}/{end_dt}"

    try:
        sec = {
            "threat_intel_hits": query_log_analytics("AZFWThreatIntel | summarize total_hits = count() by Action", timespan),
            "top_threat_intel_ips": query_log_analytics("AZFWThreatIntel | summarize count_ = count() by SourceIp | top 10 by count_", timespan),
            "top_denied_ips": query_log_analytics("AZFWNetworkRule | where Action == 'Deny' | summarize count_ = count() by SourceIp | top 10 by count_", timespan),
            "incidents_by_severity": query_log_analytics("SecurityIncident | summarize count() by Severity", timespan),
            "alerts_by_severity": query_log_analytics("SecurityAlert | summarize count() by AlertSeverity", timespan),
        }
    except Exception:
        sec = {}

    try:
        cf_threats_vals = query_metric("cloudflare.threats.all", "*", start, end, aggregation="sum")
        cf = {
            "total_threats": total(cf_threats_vals),
            "bot_traffic": {
                "badhost": total(query_metric("cloudflare.requests.ip_class", "ip_class:badhost", start, end, aggregation="sum")),
                "tor": total(query_metric("cloudflare.requests.ip_class", "ip_class:tor", start, end, aggregation="sum")),
            }
        }
    except Exception:
        cf = {}

    try:
        compliance = query_resource_graph("""
            patchassessmentresources
            | where type =~ "microsoft.compute/virtualmachines/patchassessmentresults"
            | extend properties = parse_json(properties)
            | extend critical = toint(properties.availablePatchCountByClassification.critical)
            | extend security = toint(properties.availablePatchCountByClassification.security)
            | parse id with * 'achines/' resourceName '/patchAssessmentResults/' *
            | extend compliant = iff(critical == 0 and security == 0, true, false)
            | summarize totalVMs = count(), compliantVMs = countif(compliant == true)
            | extend compliancePercent = round(100.0 * compliantVMs / totalVMs, 1)
        """)
        non_compliant = query_resource_graph("""
            patchassessmentresources
            | where type =~ "microsoft.compute/virtualmachines/patchassessmentresults"
            | extend properties = parse_json(properties)
            | extend critical = toint(properties.availablePatchCountByClassification.critical)
            | extend security = toint(properties.availablePatchCountByClassification.security)
            | parse id with * 'achines/' resourceName '/patchAssessmentResults/' *
            | where critical > 0 or security > 0
            | project resourceName, critical, security
            | order by critical desc
        """)
        patches_applied = query_resource_graph(f"""
            patchinstallationresources
            | where type =~ "microsoft.compute/virtualmachines/patchinstallationresults"
            | where properties.lastModifiedDateTime >= datetime({start_dt}) and properties.lastModifiedDateTime < datetime({end_dt})
            | extend installedPatches = toint(properties.installedPatchCount)
            | parse id with * 'achines/' resourceName '/patchInstallationResults/' *
            | summarize totalInstalled = sum(installedPatches)
        """)
        patch = {
            "compliance_summary": compliance[0] if compliance else {},
            "non_compliant_vms": non_compliant,
            "patches_applied_this_month": patches_applied[0] if patches_applied else {"totalInstalled": 0},
        }
    except Exception:
        patch = {}

    try:
        tag = "kube_cluster_name:aks-pab-prod-ne"
        k8s = {
            "container_restarts_total": total(query_metric("kubernetes.containers.restarts", tag, start, end)),
            "node_count_latest": latest(query_metric("kubernetes_state.node.count", tag, start, end)),
            "containers_terminated_total": total(query_metric("kubernetes_state.container.status_report.count.terminated", tag, start, end)),
            "containers_waiting_total": total(query_metric("kubernetes_state.container.status_report.count.waiting", tag, start, end)),
        }
    except Exception:
        k8s = {}

    try:
        shards = [
            "hostnameport:pab-prod-shard-00-00.example.mongodb.net:27017",
            "hostnameport:pab-prod-shard-00-01.example.mongodb.net:27017",
            "hostnameport:pab-prod-shard-00-02.example.mongodb.net:27017",
        ]
        mongo = {}
        for shard in shards:
            shard_name = shard.split(":")[1].split(".")[0]
            disk_used_val = latest(query_metric("mongodb.atlas.system.disk.space.used", shard, start, end))
            mongo[shard_name] = {
                "connections_avg": avg(query_metric("mongodb.atlas.connections.current", shard, start, end)),
                "disk_used_latest_gb": round(disk_used_val / 1e9, 2) if disk_used_val else None,
                "disk_iops_avg": avg(query_metric("mongodb.atlas.system.disk.iops.total", shard, start, end)),
                "replication_health": latest(query_metric("mongodb.atlas.replstatus.health", shard, start, end)),
                "replication_lag_avg_seconds": avg(query_metric("mongodb.atlas.replset.replicationlag", shard, start, end)),
            }
    except Exception:
        mongo = {}

    try:
        pg_tag = "name:psql-pab-prod-ne"
        pg_storage_val = latest(query_metric("azure.dbforpostgresql_flexibleservers.storage_used", pg_tag, start, end))
        pg = {
            "connections_avg": avg(query_metric("azure.dbforpostgresql_flexibleservers.active_connections", pg_tag, start, end)),
            "storage_used_latest_gb": round(pg_storage_val / 1e9, 2) if pg_storage_val else None,
        }
    except Exception:
        pg = {}

    try:
        sb_tag = "name:sbns-pab-prod-ne"
        sb = {
            "incoming_messages_total": total(query_metric("azure.servicebus_namespaces.incoming_messages", sb_tag, start, end, aggregation="sum")),
            "outgoing_messages_total": total(query_metric("azure.servicebus_namespaces.outgoing_messages", sb_tag, start, end, aggregation="sum")),
            "dead_lettered_messages_avg": avg(query_metric("azure.servicebus_namespaces.count_of_dead_lettered_messages_in_a_queue", sb_tag, start, end)),
        }
    except Exception:
        sb = {}

    try:
        vm_tag = "host:vmopraprodne"
        vm_avail = avg(query_metric("azure.vm.vm_availability_metric_preview", vm_tag, start, end))
        vm = {
            "availability_avg_percent": round(vm_avail * 100, 2) if vm_avail else None,
            "cpu_avg_percent": avg(query_metric("azure.vm.percentage_cpu", vm_tag, start, end)),
            "disk_read_avg_bytes_sec": avg(query_metric("azure.vm.os_disk_read_bytes_sec", vm_tag, start, end)),
        }
    except Exception:
        vm = {}

    notes = {}
    for section in NOTES_SECTIONS:
        notes[section] = read_notes(section, month_offset).get("content", "")

    # Month label
    now = datetime.now(timezone.utc)
    m = now.month + month_offset
    y = now.year
    if m <= 0:
        m += 12
        y -= 1
    month_label = datetime(y, m, 1).strftime("%B %Y")

    # RAG calculations (mirrors JS logic)
    hits = sec.get("threat_intel_hits", [{}])[0].get("total_hits", 0) if sec.get("threat_intel_hits") else 0
    incidents = len(sec.get("incidents_by_severity", []))
    fw_status = "red" if incidents > 0 else ("amber" if hits > 5 else "green")

    cf_threats = cf.get("total_threats") or 0
    cf_status = "green" if cf_threats == 0 else ("amber" if cf_threats <= 100 else "red")

    pct = (patch.get("compliance_summary") or {}).get("compliancePercent") or 0
    patch_status = "green" if pct >= 100 else ("amber" if pct >= 80 else "red")

    restarts = k8s.get("container_restarts_total") or 0
    k8s_status = "green" if restarts == 0 else ("amber" if restarts <= 5 else "red")

    pg_status = "green"

    dl = sb.get("dead_lettered_messages_avg") or 0
    sb_status = "green" if dl == 0 else ("amber" if dl <= 10 else "red")

    avail = vm.get("availability_avg_percent") or 0
    vm_status = "green" if avail >= 100 else ("amber" if avail >= 99 else "red")

    mongo_health = "green"
    for s in (mongo or {}).values():
        if s.get("replication_health") != 1 or (s.get("replication_lag_avg_seconds") or 0) > 5:
            mongo_health = "red"
            break
        elif (s.get("replication_lag_avg_seconds") or 0) > 1:
            mongo_health = "amber"

    rag_summary = [
        ("Firewall", fw_status),
        ("Cloudflare", cf_status),
        ("Patching", patch_status),
        ("Kubernetes", k8s_status),
        ("MongoDB", mongo_health),
        ("PostgreSQL", pg_status),
        ("Service Bus", sb_status),
        ("Virtual Machines", vm_status),
    ]

    # ── Build PDF ──
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=20*mm, bottomMargin=20*mm,
        title=f"Infrastructure Health Report — {month_label}",
    )

    BG = colors.HexColor("#f4f3ef")
    DARK = colors.HexColor("#1a1917")
    MID = colors.HexColor("#6b6860")
    LIGHT = colors.HexColor("#9c9a94")
    BORDER = colors.HexColor("#e8e6e0")
    SURF2 = colors.HexColor("#f9f8f5")

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", fontSize=20, leading=24, textColor=DARK, spaceAfter=4, fontName="Helvetica-Bold")
    h2 = ParagraphStyle("h2", fontSize=13, leading=17, textColor=DARK, spaceBefore=14, spaceAfter=6, fontName="Helvetica-Bold")
    h3 = ParagraphStyle("h3", fontSize=10, leading=13, textColor=MID, spaceBefore=10, spaceAfter=4, fontName="Helvetica-Bold")
    body = ParagraphStyle("body", fontSize=9, leading=13, textColor=DARK, fontName="Helvetica")
    small = ParagraphStyle("small", fontSize=8, leading=11, textColor=MID, fontName="Helvetica")
    label_s = ParagraphStyle("label", fontSize=7, leading=9, textColor=LIGHT, fontName="Helvetica-Bold")

    story = []

    def hr():
        story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceAfter=8, spaceBefore=4))

    def section_title(txt):
        story.append(Spacer(1, 4))
        story.append(Paragraph(txt.upper(), ParagraphStyle("st", fontSize=8, leading=10, textColor=LIGHT, fontName="Helvetica-Bold", spaceBefore=16, spaceAfter=8, letterSpacing=1)))

    def notes_block(key):
        content = notes.get(key, "").strip()
        if content:
            story.append(Paragraph("Notes", label_s))
            story.append(Paragraph(content.replace("\n", "<br/>"), body))
            story.append(Spacer(1, 6))

    def _rag_cell(status):
        hex_col = {"green": "2d7a4f", "amber": "b45309", "red": "c0392b"}.get(status, "1a1917")
        lbl = rag_label(status)
        return Paragraph(f'<font color="#{hex_col}"><b>{lbl}</b></font>', body)

    # ── Cover / header ──
    story.append(Paragraph("Infrastructure &amp; Platform Health Report", h1))
    story.append(Paragraph(month_label, ParagraphStyle("sub", fontSize=13, leading=16, textColor=MID, fontName="Helvetica", spaceAfter=6)))
    story.append(Paragraph(f"Generated {datetime.now(timezone.utc).strftime('%d %B %Y, %H:%M UTC')}", small))
    story.append(Spacer(1, 8))
    hr()

    # ── 1. Executive Summary ──
    story.append(Paragraph("1. Executive Summary", h2))
    story.append(Paragraph("RAG status across all monitored service areas for the reporting period.", body))
    story.append(Spacer(1, 6))

    rag_data = [["Service area", "Status"]]
    for name, status in rag_summary:
        rag_data.append([Paragraph(name, body), _rag_cell(status)])

    rag_table = Table(rag_data, colWidths=["70%", "30%"])
    rag_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, SURF2]),
        ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(rag_table)
    story.append(PageBreak())

    # ── 2. Security ──
    story.append(Paragraph("2. Security", h2))
    hr()

    section_title("Firewall &amp; Sentinel")
    denied_total = sum(ip.get("count_", 0) for ip in (sec.get("top_denied_ips") or []))
    alerts_count = len(sec.get("alerts_by_severity") or [])
    fw_data = [
        ["Metric", "Value"],
        ["Threat intel hits", str(hits)],
        ["Denied connections (top IPs)", str(denied_total)],
        ["Security incidents", str(incidents)],
        ["Security alerts", str(alerts_count)],
    ]
    fw_table = Table(fw_data, colWidths=["60%", "40%"])
    fw_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, SURF2]),
        ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica"),
    ]))
    story.append(fw_table)
    notes_block("security")

    section_title("Cloudflare")
    story.append(Paragraph(f"Total threats: <b>{cf_threats:,}</b> &nbsp; Bad host: <b>{(cf.get('bot_traffic') or {}).get('badhost') or 0:,}</b> &nbsp; Tor: <b>{(cf.get('bot_traffic') or {}).get('tor') or 0:,}</b>", body))
    story.append(Spacer(1, 4))

    section_title("Vulnerability Scanning")
    vuln_notes = notes.get("vulnerability", "").strip()
    story.append(Paragraph(vuln_notes.replace("\n", "<br/>") if vuln_notes else "No vulnerability scanning notes recorded for this period.", body))
    story.append(Spacer(1, 4))

    section_title("Patching")
    cs = patch.get("compliance_summary") or {}
    story.append(Paragraph(
        f"Compliance: <b>{cs.get('compliancePercent', 0)}%</b> ({cs.get('compliantVMs', 0)} of {cs.get('totalVMs', 0)} VMs) &nbsp; "
        f"Patches applied this month: <b>{(patch.get('patches_applied_this_month') or {}).get('totalInstalled', 0)}</b>",
        body
    ))
    non_compliant = patch.get("non_compliant_vms") or []
    if non_compliant:
        story.append(Spacer(1, 4))
        nc_data = [["VM Name", "Critical", "Security"]] + [[vm_r.get("resourceName",""), str(vm_r.get("critical",0)), str(vm_r.get("security",0))] for vm_r in non_compliant]
        nc_table = Table(nc_data, colWidths=["60%", "20%", "20%"])
        nc_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, SURF2]),
            ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(nc_table)
    story.append(PageBreak())

    # ── 3. Reliability & Uptime ──
    story.append(Paragraph("3. Reliability &amp; Uptime", h2))
    hr()

    section_title("Kubernetes — aks-pab-prod-ne")
    story.append(Paragraph(
        f"Nodes: <b>{k8s.get('node_count_latest') or '—'}</b> &nbsp; "
        f"Container restarts: <b>{int(k8s.get('container_restarts_total') or 0)}</b> &nbsp; "
        f"Terminated: <b>{int(k8s.get('containers_terminated_total') or 0)}</b> &nbsp; "
        f"Waiting: <b>{int(k8s.get('containers_waiting_total') or 0)}</b>",
        body
    ))
    notes_block("reliability")

    section_title("MongoDB — pab-prod")
    for shard_name, s in (mongo or {}).items():
        story.append(Paragraph(
            f"<b>{shard_name}</b> — Connections avg: {s.get('connections_avg') or '—'} &nbsp; "
            f"Disk used: {s.get('disk_used_latest_gb') or '—'} GB &nbsp; "
            f"Repl health: {'OK' if s.get('replication_health') == 1 else 'DEGRADED'} &nbsp; "
            f"Repl lag avg: {s.get('replication_lag_avg_seconds') or '—'}s",
            body
        ))
        story.append(Spacer(1, 3))

    section_title("PostgreSQL — psql-pab-prod-ne")
    story.append(Paragraph(
        f"Avg connections: <b>{pg.get('connections_avg') or '—'}</b> &nbsp; Storage used: <b>{pg.get('storage_used_latest_gb') or '—'} GB</b>",
        body
    ))

    section_title("Service Bus — sbns-pab-prod-ne")
    story.append(Paragraph(
        f"Incoming: <b>{int(sb.get('incoming_messages_total') or 0):,}</b> &nbsp; "
        f"Outgoing: <b>{int(sb.get('outgoing_messages_total') or 0):,}</b> &nbsp; "
        f"Dead lettered (avg): <b>{sb.get('dead_lettered_messages_avg') or 0}</b>",
        body
    ))

    section_title("Virtual Machines — vmopraprodne")
    story.append(Paragraph(
        f"Availability: <b>{vm.get('availability_avg_percent') or '—'}%</b> &nbsp; "
        f"Avg CPU: <b>{vm.get('cpu_avg_percent') or '—'}%</b> &nbsp; "
        f"Disk read: <b>{vm.get('disk_read_avg_bytes_sec') or '—'} bytes/s</b>",
        body
    ))
    story.append(PageBreak())

    # ── 4. Upcoming Work ──
    story.append(Paragraph("4. Upcoming Work", h2))
    hr()

    section_title("Scheduled Maintenance")
    sm = notes.get("upcoming-scheduled-maintenance", "").strip()
    story.append(Paragraph(sm.replace("\n", "<br/>") if sm else "None recorded.", body))

    section_title("Ongoing Operational Tasks")
    ot = notes.get("upcoming-operational-tasks", "").strip()
    story.append(Paragraph(ot.replace("\n", "<br/>") if ot else "None recorded.", body))

    section_title("Projects")
    pr = notes.get("upcoming-projects", "").strip()
    story.append(Paragraph(pr.replace("\n", "<br/>") if pr else "None recorded.", body))

    # ── Build ──
    doc.build(story)
    buf.seek(0)

    filename = f"InfraHealth-Report-{month_label.replace(' ', '-')}.pdf"
    return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name=filename)


# ─── Dashboard ──────────────────────────────────────────────

@app.route("/dashboard")
def dashboard():
    return send_from_directory('.', 'dashboard.html')


# ─── Health ─────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/")
def index():
    return "Infrastructure Health - App Service Running"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)