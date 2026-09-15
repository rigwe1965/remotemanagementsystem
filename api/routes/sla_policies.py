"""SLA Policy CRUD — admin-only configuration of response/resolution targets per priority."""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from extensions import db
from models.sla_policy import SLAPolicy

sla_bp = Blueprint("sla_policies", __name__)

_VALID_PRIORITIES = {"critical", "high", "medium", "low"}


def _require_role(*roles):
    claims = get_jwt()
    if claims.get("role") == "superadmin":
        return None
    if claims.get("role") not in roles:
        return jsonify({"error": "Insufficient permissions"}), 403
    return None


@sla_bp.route("/", methods=["GET"])
@jwt_required()
def list_policies():
    customer_id = request.args.get("customer_id")
    query = SLAPolicy.query
    if customer_id:
        query = query.filter(
            (SLAPolicy.customer_id == customer_id) | (SLAPolicy.customer_id == None)  # noqa: E711
        )
    else:
        query = query.filter(SLAPolicy.customer_id == None)  # noqa: E711
    policies = query.order_by(SLAPolicy.priority).all()
    return jsonify([p.to_dict() for p in policies]), 200


@sla_bp.route("/", methods=["POST"])
@jwt_required()
def create_policy():
    err = _require_role("admin")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    priority = (data.get("priority") or "").lower()
    if priority not in _VALID_PRIORITIES:
        return jsonify({"error": f"priority must be one of {sorted(_VALID_PRIORITIES)}"}), 400

    response_hours = data.get("response_hours")
    resolution_hours = data.get("resolution_hours")
    if not isinstance(response_hours, int) or not isinstance(resolution_hours, int):
        return jsonify({"error": "response_hours and resolution_hours must be integers"}), 400
    if response_hours < 1 or resolution_hours < 1:
        return jsonify({"error": "hours must be >= 1"}), 400

    customer_id = data.get("customer_id") or None

    existing = SLAPolicy.query.filter_by(customer_id=customer_id, priority=priority).first()
    if existing:
        return jsonify({"error": f"SLA policy for priority '{priority}' already exists for this scope"}), 409

    policy = SLAPolicy(
        customer_id=customer_id,
        priority=priority,
        response_hours=response_hours,
        resolution_hours=resolution_hours,
    )
    db.session.add(policy)
    db.session.commit()
    return jsonify(policy.to_dict()), 201


@sla_bp.route("/<policy_id>", methods=["PUT"])
@jwt_required()
def update_policy(policy_id):
    err = _require_role("admin")
    if err:
        return err
    policy = db.get_or_404(SLAPolicy, policy_id)
    data = request.get_json(silent=True) or {}
    if "response_hours" in data:
        h = data["response_hours"]
        if not isinstance(h, int) or h < 1:
            return jsonify({"error": "response_hours must be integer >= 1"}), 400
        policy.response_hours = h
    if "resolution_hours" in data:
        h = data["resolution_hours"]
        if not isinstance(h, int) or h < 1:
            return jsonify({"error": "resolution_hours must be integer >= 1"}), 400
        policy.resolution_hours = h
    db.session.commit()
    return jsonify(policy.to_dict()), 200


@sla_bp.route("/<policy_id>", methods=["DELETE"])
@jwt_required()
def delete_policy(policy_id):
    err = _require_role("admin")
    if err:
        return err
    policy = db.get_or_404(SLAPolicy, policy_id)
    if policy.customer_id is None:
        return jsonify({"error": "Global default SLA policies cannot be deleted — update them instead"}), 400
    db.session.delete(policy)
    db.session.commit()
    return jsonify({"message": "SLA policy deleted"}), 200
