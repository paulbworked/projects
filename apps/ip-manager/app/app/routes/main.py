from flask import Blueprint, render_template, request, redirect, url_for, flash
from app import db
from app.models import AddressSpace, VirtualNetwork, VNetCIDR, Subnet, IPAddress, FirewallIP, MasterCIDR
import ipaddress

main = Blueprint("main", __name__)

def calculate_free_space(parent_cidr, child_cidrs):
    """Calculate unallocated gaps between child CIDRs within a parent CIDR."""
    try:
        parent = ipaddress.ip_network(parent_cidr, strict=False)
    except ValueError:
        return []

    # Parse and sort child networks, skip any that don't fit in the parent
    children = []
    for cidr in child_cidrs:
        try:
            net = ipaddress.ip_network(cidr, strict=False)
            if net.subnet_of(parent):
                children.append(net)
        except ValueError:
            continue

    if not children:
        return [str(parent)]

    children.sort(key=lambda x: x.network_address)

    free = []
    current = parent.network_address

    for child in children:
        if current < child.network_address:
            # There's a gap before this child
            gap_start = int(current)
            gap_end = int(child.network_address) - 1
            try:
                gap_networks = list(ipaddress.summarize_address_range(
                    ipaddress.ip_address(gap_start),
                    ipaddress.ip_address(gap_end)
                ))
                free.extend([str(n) for n in gap_networks])
            except Exception:
                pass
        # Move past this child
        next_addr = ipaddress.ip_address(int(child.broadcast_address) + 1)
        if next_addr > current:
            current = next_addr

    # Check for gap after the last child
    parent_end = parent.broadcast_address
    if current <= parent_end:
        try:
            gap_networks = list(ipaddress.summarize_address_range(current, parent_end))
            free.extend([str(n) for n in gap_networks])
        except Exception:
            pass

    return free

# ── Dashboard ──────────────────────────────────────────────────────────────

@main.route("/")
def index():
    address_spaces = AddressSpace.query.all()
    total_vnets    = VirtualNetwork.query.count()
    total_subnets  = Subnet.query.count()
    free_subnets   = Subnet.query.filter_by(status="free").count()
    firewall_ips   = FirewallIP.query.all()
    ip_addresses   = IPAddress.query.all()
    return render_template("index.html",
        address_spaces=address_spaces,
        total_vnets=total_vnets,
        total_subnets=total_subnets,
        free_subnets=free_subnets,
        firewall_ips=firewall_ips,
        ip_addresses=ip_addresses
    )

# ── Address Spaces ─────────────────────────────────────────────────────────

@main.route("/address-space/add", methods=["GET", "POST"])
def add_address_space():
    if request.method == "POST":
        space = AddressSpace(
            name        = request.form["name"],
            description = request.form.get("description")
        )
        db.session.add(space)
        db.session.commit()
        flash("Address space added successfully", "success")
        return redirect(url_for("main.index"))
    return render_template("add_address_space.html")

@main.route("/address-space/<int:id>/delete", methods=["POST"])
def delete_address_space(id):
    space = AddressSpace.query.get_or_404(id)
    db.session.delete(space)
    db.session.commit()
    flash("Address space removed", "success")
    return redirect(url_for("main.index"))

@main.route("/address-space/<int:id>/edit", methods=["GET", "POST"])
def edit_address_space(id):
    space = AddressSpace.query.get_or_404(id)
    if request.method == "POST":
        space.name        = request.form["name"]
        space.description = request.form.get("description")
        db.session.commit()
        flash("Address space updated successfully", "success")
        return redirect(url_for("main.index"))
    return render_template("edit_address_space.html", space=space)

# ── Virtual Networks ───────────────────────────────────────────────────────

def _save_vnet(resource_type):
    """Shared logic for adding VNet, VPN and vWAN."""
    from app.models import VNetCIDR
    vnet = VirtualNetwork(
        name             = request.form["name"],
        region           = request.form.get("region"),
        resource_group   = request.form.get("resource_group"),
        resource_type    = resource_type,
        environment      = request.form["environment"],
        service          = request.form.get("service"),
        address_space_id = request.form["address_space_id"]
    )
    db.session.add(vnet)
    db.session.flush()  # get vnet.id before committing

    # Save all non-empty CIDRs
    cidrs = request.form.getlist("cidr")
    for cidr in cidrs:
        cidr = cidr.strip()
        if cidr:
            db.session.add(VNetCIDR(cidr=cidr, vnet_id=vnet.id))

    db.session.commit()

@main.route("/vnet/add", methods=["GET", "POST"])
def add_vnet():
    if request.method == "POST":
        _save_vnet("VNet")
        flash("Virtual network added successfully", "success")
        return redirect(url_for("main.index"))
    address_spaces = AddressSpace.query.all()
    return render_template("add_vnet.html", address_spaces=address_spaces, resource_type="VNet")

@main.route("/vpn/add", methods=["GET", "POST"])
def add_vpn():
    if request.method == "POST":
        _save_vnet("VPN")
        flash("VPN gateway added successfully", "success")
        return redirect(url_for("main.index"))
    address_spaces = AddressSpace.query.all()
    return render_template("add_vnet.html", address_spaces=address_spaces, resource_type="VPN")

@main.route("/vwan/add", methods=["GET", "POST"])
def add_vwan():
    if request.method == "POST":
        _save_vnet("vWAN")
        flash("vWAN added successfully", "success")
        return redirect(url_for("main.index"))
    address_spaces = AddressSpace.query.all()
    return render_template("add_vnet.html", address_spaces=address_spaces, resource_type="vWAN")

@main.route("/vnet/<int:id>/delete", methods=["POST"])
def delete_vnet(id):
    vnet = VirtualNetwork.query.get_or_404(id)
    db.session.delete(vnet)
    db.session.commit()
    flash("Virtual network removed", "success")
    return redirect(url_for("main.index"))

# ── Subnets ────────────────────────────────────────────────────────────────

@main.route("/subnet/add", methods=["GET", "POST"])
def add_subnet():
    if request.method == "POST":
        subnet = Subnet(
            name         = request.form["name"],
            cidr         = request.form["cidr"],
            status       = request.form["status"],
            allocated_to = request.form.get("allocated_to"),
            purpose      = request.form.get("purpose"),
            environment  = request.form.get("environment"),
            service      = request.form.get("service"),
            vnet_id      = request.form["vnet_id"]
        )
        db.session.add(subnet)
        db.session.commit()
        flash("Subnet added successfully", "success")
        return redirect(url_for("main.index"))
    vnets = VirtualNetwork.query.all()
    return render_template("add_subnet.html", vnets=vnets)

@main.route("/subnet/<int:id>/edit", methods=["GET", "POST"])
def edit_subnet(id):
    subnet = Subnet.query.get_or_404(id)
    if request.method == "POST":
        subnet.status       = request.form["status"]
        subnet.allocated_to = request.form.get("allocated_to")
        subnet.purpose      = request.form.get("purpose")
        subnet.environment  = request.form.get("environment")
        subnet.service      = request.form.get("service")
        db.session.commit()
        flash("Subnet updated successfully", "success")
        return redirect(url_for("main.index"))
    return render_template("edit_subnet.html", subnet=subnet)

@main.route("/subnet/<int:id>/delete", methods=["POST"])
def delete_subnet(id):
    subnet = Subnet.query.get_or_404(id)
    db.session.delete(subnet)
    db.session.commit()
    flash("Subnet removed", "success")
    return redirect(url_for("main.index"))

# ── IP Addresses ───────────────────────────────────────────────────────────

@main.route("/ip/add", methods=["GET", "POST"])
def add_ip():
    if request.method == "POST":
        ip = IPAddress(
            address      = request.form["address"],
            service_name = request.form["service_name"],
            description  = request.form.get("description"),
            subnet_id    = request.form["subnet_id"]
        )
        db.session.add(ip)
        db.session.commit()
        flash("IP address added successfully", "success")
        return redirect(url_for("main.index"))
    subnets = Subnet.query.all()
    return render_template("add_ip.html", subnets=subnets)

@main.route("/ip/<int:id>/delete", methods=["POST"])
def delete_ip(id):
    ip = IPAddress.query.get_or_404(id)
    db.session.delete(ip)
    db.session.commit()
    flash("IP address removed", "success")
    return redirect(url_for("main.index"))

# ── Firewall IPs ───────────────────────────────────────────────────────────

@main.route("/firewall/add", methods=["GET", "POST"])
def add_firewall_ip():
    if request.method == "POST":
        fip = FirewallIP(
            public_ip         = request.form["public_ip"],
            label             = request.form["label"],
            mapped_to_service = request.form.get("mapped_to_service"),
            firewall_rule_ref = request.form.get("firewall_rule_ref"),
            notes             = request.form.get("notes")
        )
        db.session.add(fip)
        db.session.commit()
        flash("Firewall IP added successfully", "success")
        return redirect(url_for("main.index"))
    return render_template("add_firewall_ip.html")

@main.route("/firewall/<int:id>/delete", methods=["POST"])
def delete_firewall_ip(id):
    fip = FirewallIP.query.get_or_404(id)
    db.session.delete(fip)
    db.session.commit()
    flash("Firewall IP removed", "success")
    return redirect(url_for("main.index"))

# ── Free Space ─────────────────────────────────────────────────────────────

@main.route("/free-space")
def free_space():
    address_spaces = AddressSpace.query.all()
    master_cidrs   = MasterCIDR.query.all()

    # Collect all VNet CIDRs across the entire app
    all_vnet_cidrs = [c.cidr for space in address_spaces for v in space.vnets for c in v.cidrs]

    # Calculate free ranges within each master CIDR block
    master_free = []
    for mc in master_cidrs:
        gaps = calculate_free_space(mc.cidr, all_vnet_cidrs)
        master_free.append({
            'master': mc,
            'free_ranges': gaps
        })

    # Per-VNet free space (gaps between subnets)
    results = []
    for space in address_spaces:
        vnet_details = []
        for vnet in space.vnets:
            subnet_cidrs = [s.cidr for s in vnet.subnets]
            vnet_free = []
            for vnet_cidr in vnet.cidrs:
                gaps = calculate_free_space(vnet_cidr.cidr, subnet_cidrs)
                vnet_free.extend(gaps)
            vnet_details.append({
                'vnet': vnet,
                'free_ranges': vnet_free
            })
        results.append({
            'space': space,
            'vnet_details': vnet_details
        })

    return render_template("free_space.html", results=results, master_free=master_free)


# ── Settings ───────────────────────────────────────────────────────────────

@main.route("/settings")
def settings():
    master_cidrs = MasterCIDR.query.all()
    return render_template("settings.html", master_cidrs=master_cidrs)

@main.route("/settings/cidr/add", methods=["POST"])
def add_master_cidr():
    cidr  = request.form.get("cidr", "").strip()
    label = request.form.get("label", "").strip()
    if cidr:
        db.session.add(MasterCIDR(cidr=cidr, label=label or None))
        db.session.commit()
        flash("Master CIDR block added", "success")
    return redirect(url_for("main.settings"))

@main.route("/settings/cidr/<int:id>/delete", methods=["POST"])
def delete_master_cidr(id):
    mc = MasterCIDR.query.get_or_404(id)
    db.session.delete(mc)
    db.session.commit()
    flash("Master CIDR block removed", "success")
    return redirect(url_for("main.settings"))

