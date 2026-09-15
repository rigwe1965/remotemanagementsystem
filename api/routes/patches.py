from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from datetime import datetime, timezone
from extensions import db
from models.patch import PatchRecord, PatchPolicy

patches_bp = Blueprint("patches", __name__)


def _require_role(*roles):
    claims = get_jwt()
    if claims.get("role") == "superadmin":
        return None  # superadmin bypasses all role checks
    if claims.get("role") not in roles:
        return jsonify({"error": "Insufficient permissions"}), 403
    return None


@patches_bp.route("/", methods=["GET"])
@jwt_required()
def list_patches():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 200)
    device_id = request.args.get("device_id")
    status = request.args.get("status")
    patch_type = request.args.get("type")

    query = PatchRecord.query
    if device_id:
        query = query.filter_by(device_id=device_id)
    if status:
        query = query.filter_by(status=status)
    if patch_type:
        query = query.filter_by(patch_type=patch_type)

    paginated = query.order_by(PatchRecord.created_at.desc()).paginate(page=page, per_page=per_page)
    return jsonify({
        "items": [p.to_dict() for p in paginated.items],
        "total": paginated.total,
        "page": page,
    }), 200


@patches_bp.route("/pending", methods=["GET"])
@jwt_required()
def pending_patches():
    patches = PatchRecord.query.filter_by(status="pending").order_by(
        PatchRecord.created_at.desc()
    ).limit(200).all()
    return jsonify([p.to_dict() for p in patches]), 200


@patches_bp.route("/approve", methods=["POST"])
@jwt_required()
def approve_patches():
    err = _require_role("admin", "technician")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    patch_ids = data.get("patch_ids", [])
    if not patch_ids:
        return jsonify({"error": "patch_ids required"}), 400

    updated = PatchRecord.query.filter(
        PatchRecord.id.in_(patch_ids),
        PatchRecord.status == "pending",
    ).all()
    for p in updated:
        p.status = "approved"
        p.deployed_by = get_jwt_identity()
    db.session.commit()
    return jsonify({"approved": len(updated)}), 200


@patches_bp.route("/summary", methods=["GET"])
@jwt_required()
def patch_summary():
    from sqlalchemy import func
    rows = db.session.query(
        PatchRecord.status, func.count(PatchRecord.id)
    ).group_by(PatchRecord.status).all()
    counts = dict(rows)
    total = sum(counts.values())
    deployed = counts.get("deployed", 0)
    return jsonify({
        "total": total,
        "pending": counts.get("pending", 0),
        "approved": counts.get("approved", 0),
        "deployed": deployed,
        "failed": counts.get("failed", 0),
        "compliance_pct": round((deployed / total * 100) if total else 0, 1),
    }), 200


# Patch Policies

@patches_bp.route("/policies", methods=["GET"])
@jwt_required()
def list_policies():
    policies = PatchPolicy.query.all()
    return jsonify([p.to_dict() for p in policies]), 200


@patches_bp.route("/policies", methods=["POST"])
@jwt_required()
def create_policy():
    err = _require_role("admin", "technician")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if not data.get("name"):
        return jsonify({"error": "name required"}), 400
    policy = PatchPolicy(
        name=data["name"],
        customer_id=data.get("customer_id"),
        device_group_id=data.get("device_group_id"),
        auto_approve_critical=data.get("auto_approve_critical", True),
        auto_approve_security=data.get("auto_approve_security", True),
        auto_approve_service_packs=data.get("auto_approve_service_packs", False),
        auto_approve_drivers=data.get("auto_approve_drivers", False),
        reboot_behavior=data.get("reboot_behavior", "prompt"),
        winget_enabled=data.get("winget_enabled", True),
        choco_enabled=data.get("choco_enabled", False),
        excluded_software=data.get("excluded_software", []),
        software_bundles=data.get("software_bundles", []),
    )
    db.session.add(policy)
    db.session.commit()
    return jsonify(policy.to_dict()), 201


@patches_bp.route("/policies/<policy_id>", methods=["PUT"])
@jwt_required()
def update_policy(policy_id):
    err = _require_role("admin", "technician")
    if err:
        return err
    policy = db.get_or_404(PatchPolicy, policy_id)
    data = request.get_json(silent=True) or {}
    for field in ["name", "auto_approve_critical", "auto_approve_security",
                  "auto_approve_service_packs", "auto_approve_drivers",
                  "reboot_behavior", "winget_enabled", "choco_enabled",
                  "excluded_software", "software_bundles", "upgrade_os"]:
        if field in data:
            setattr(policy, field, data[field])
    db.session.commit()
    return jsonify(policy.to_dict()), 200


@patches_bp.route("/policies/<policy_id>", methods=["DELETE"])
@jwt_required()
def delete_policy(policy_id):
    err = _require_role("admin")
    if err:
        return err
    policy = db.get_or_404(PatchPolicy, policy_id)
    db.session.delete(policy)
    db.session.commit()
    return jsonify({"message": "Policy deleted"}), 200
