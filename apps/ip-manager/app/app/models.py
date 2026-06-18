from app import db
from datetime import datetime

class MasterCIDR(db.Model):
    __tablename__ = "master_cidrs"

    id          = db.Column(db.Integer, primary_key=True)
    cidr        = db.Column(db.String(50), nullable=False)
    label       = db.Column(db.String(100))
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)


class AddressSpace(db.Model):
    __tablename__ = "address_spaces"

    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255))
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    vnets       = db.relationship("VirtualNetwork", backref="address_space", lazy=True)


class VirtualNetwork(db.Model):
    __tablename__ = "virtual_networks"

    id               = db.Column(db.Integer, primary_key=True)
    name             = db.Column(db.String(100), nullable=False)
    region           = db.Column(db.String(100))
    resource_group   = db.Column(db.String(100))
    resource_type    = db.Column(db.String(50))   # VNet, vWAN, VPN
    environment      = db.Column(db.String(50))   # ops, prod, dev, unq, qual, val, dr
    service          = db.Column(db.String(100))  # e.g. Operations, Axion, OPRA
    address_space_id = db.Column(db.Integer, db.ForeignKey("address_spaces.id"), nullable=False)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)

    cidrs            = db.relationship("VNetCIDR", backref="vnet", lazy=True, cascade="all, delete-orphan")
    subnets          = db.relationship("Subnet", backref="vnet", lazy=True)


class VNetCIDR(db.Model):
    __tablename__ = "vnet_cidrs"

    id         = db.Column(db.Integer, primary_key=True)
    cidr       = db.Column(db.String(50), nullable=False)
    vnet_id    = db.Column(db.Integer, db.ForeignKey("virtual_networks.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Subnet(db.Model):
    __tablename__ = "subnets"

    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(100), nullable=False)
    cidr         = db.Column(db.String(50), nullable=False)
    status       = db.Column(db.String(50), default="free")  # free, reserved, assigned
    allocated_to = db.Column(db.String(100))
    purpose      = db.Column(db.String(255))
    environment  = db.Column(db.String(50))
    service      = db.Column(db.String(100))  # e.g. Operations, Axion, OPRA
    vnet_id      = db.Column(db.Integer, db.ForeignKey("virtual_networks.id"), nullable=False)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    ip_addresses = db.relationship("IPAddress", backref="subnet", lazy=True)


class IPAddress(db.Model):
    __tablename__ = "ip_addresses"

    id           = db.Column(db.Integer, primary_key=True)
    address      = db.Column(db.String(50), nullable=False)
    service_name = db.Column(db.String(100), nullable=False)
    description  = db.Column(db.String(255))
    subnet_id    = db.Column(db.Integer, db.ForeignKey("subnets.id"), nullable=False)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)


class FirewallIP(db.Model):
    __tablename__ = "firewall_ips"

    id                = db.Column(db.Integer, primary_key=True)
    public_ip         = db.Column(db.String(50), nullable=False)
    label             = db.Column(db.String(100), nullable=False)
    mapped_to_service = db.Column(db.String(100))
    firewall_rule_ref = db.Column(db.String(100))
    notes             = db.Column(db.String(255))
    created_at        = db.Column(db.DateTime, default=datetime.utcnow)
