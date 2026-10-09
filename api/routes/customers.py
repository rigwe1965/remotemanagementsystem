from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from extensions import db
from models.customer import Customer, DeviceGroup
from models.audit import AuditLog
from utils.validation import validate_body
from schemas.customers import CustomerCreateSchema, CustomerUpdateSchema, DeviceGroupCreateSchema
from utils.auth_decorators import require_role as _require_role
from utils.scope import require_customer_scope
from utils.pagination import paginated_response
import uuid
import re

customers_bp = Blueprint("customers", __name__)


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:100]


@customers_bp.route("/", methods=["GET"])
@jwt_required()
def list_customers():
    err = _require_role("admin", "technician", "viewer")
    if err:
        return err
    q = request.args.get("q", "")

    query = Customer.query.filter_by(is_active=True)
    if q:
        query = query.filter(Customer.name.ilike(f"%{q}%"))

    return paginated_response(
        query, lambda c: c.to_dict(include_counts=True),
        order_by=Customer.name, default_per_page=20, max_per_page=100,
    )


@customers_bp.route("/", methods=["POST"])
@jwt_required()
@validate_body(CustomerCreateSchema)
def create_customer():
    err = _require_role("admin", "technician")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400

    slug = _slugify(name)
    # Ensure unique slug
    base_slug = slug
    counter = 1
    while Customer.query.filter_by(slug=slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1

    customer = Customer(
        name=name,
        slug=slug,
        email=data.get("email"),
        phone=data.get("phone"),
        address=data.get("address"),
        tier=data.get("tier", "standard"),
        notes=data.get("notes"),
        registration_token_hash=str(uuid.uuid4()),
    )
    db.session.add(customer)
    db.session.commit()
    return jsonify(customer.to_dict()), 201


@customers_bp.route("/<customer_id>", methods=["GET"])
@jwt_required()
def get_customer(customer_id):
    customer = db.get_or_404(Customer, customer_id)
    err = require_customer_scope(customer_id)
    if err:
        return err
    return jsonify(customer.to_dict(include_counts=True)), 200


@customers_bp.route("/<customer_id>", methods=["PUT"])
@jwt_required()
@validate_body(CustomerUpdateSchema)
def update_customer(customer_id):
    err = _require_role("admin", "technician")
    if err:
        return err
    customer = db.get_or_404(Customer, customer_id)
    data = request.get_json(silent=True) or {}
    for field in ["name", "email", "phone", "address", "tier", "notes", "billing_day", "per_device_rate", "tax_rate"]:
        if field in data:
            setattr(customer, field, data[field])
    db.session.commit()
    return jsonify(customer.to_dict()), 200


@customers_bp.route("/<customer_id>", methods=["DELETE"])
@jwt_required()
def delete_customer(customer_id):
    err = _require_role("admin")
    if err:
        return err
    customer = db.get_or_404(Customer, customer_id)
    customer.is_active = False
    db.session.commit()
    return jsonify({"message": "Customer deactivated"}), 200


@customers_bp.route("/<customer_id>/devices", methods=["GET"])
@jwt_required()
def customer_devices(customer_id):
    db.get_or_404(Customer, customer_id)
    err = require_customer_scope(customer_id)
    if err:
        return err
    from models.device import Device, DeviceMetrics
    from sqlalchemy import func
    devices = Device.query.filter_by(customer_id=customer_id).all()
    device_ids = [d.id for d in devices]
    metrics_by_device = {}
    if device_ids:
        subq = (
            db.select(func.max(DeviceMetrics.id).label("max_id"))
            .where(DeviceMetrics.device_id.in_(device_ids))
            .group_by(DeviceMetrics.device_id)
            .subquery()
        )
        rows = db.session.execute(
            db.select(DeviceMetrics).join(subq, DeviceMetrics.id == subq.c.max_id)
        ).scalars().all()
        metrics_by_device = {m.device_id: m.to_dict() for m in rows}
    return jsonify([
        d.to_dict(include_latest_metrics=True, latest_metrics_data=metrics_by_device.get(d.id))
        for d in devices
    ]), 200


# Device Groups
@customers_bp.route("/groups", methods=["GET"])
@jwt_required()
def list_groups():
    err = _require_role("admin", "technician", "viewer")
    if err:
        return err
    customer_id = request.args.get("customer_id")
    query = DeviceGroup.query
    if customer_id:
        query = query.filter_by(customer_id=customer_id)
    return paginated_response(query, lambda g: g.to_dict(), order_by=DeviceGroup.name)


@customers_bp.route("/groups", methods=["POST"])
@jwt_required()
@validate_body(DeviceGroupCreateSchema)
def create_group():
    err = _require_role("admin", "technician")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if not data.get("name") or not data.get("customer_id"):
        return jsonify({"error": "name and customer_id required"}), 400
    group = DeviceGroup(
        customer_id=data["customer_id"],
        name=data["name"],
        description=data.get("description"),
    )
    db.session.add(group)
    db.session.commit()
    return jsonify(group.to_dict()), 201
