from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from extensions import db
from models.automation import AutomationProfile, ScheduledTaskRun
from models.device import Device
from utils.validation import validate_body
from schemas.automation import AutomationProfileCreateSchema, AutomationProfileUpdateSchema
from utils.auth_decorators import require_role as _require_role
from utils.pagination import paginated_response

automation_bp = Blueprint("automation", __name__)


@automation_bp.route("/profiles", methods=["GET"])
@jwt_required()
def list_profiles():
    err = _require_role("admin", "technician", "viewer")
    if err:
        return err
    customer_id = request.args.get("customer_id")
    query = AutomationProfile.query
    if customer_id:
        query = query.filter_by(customer_id=customer_id)
    return paginated_response(query, lambda p: p.to_dict(), order_by=AutomationProfile.name)


@automation_bp.route("/profiles", methods=["POST"])
@jwt_required()
@validate_body(AutomationProfileCreateSchema)
def create_profile():
    err = _require_role("admin", "technician")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if not data.get("name"):
        return jsonify({"error": "name required"}), 400
    profile = AutomationProfile(
        name=data["name"],
        customer_id=data.get("customer_id"),
        device_group_id=data.get("device_group_id"),
        is_active=data.get("is_active", True),
        schedule_type=data.get("schedule_type", "weekly"),
        schedule_config=data.get("schedule_config", {}),
        run_on_new_agents=data.get("run_on_new_agents", False),
        notification_emails=data.get("notification_emails", []),
        os_patch_config=data.get("os_patch_config", {}),
        software_patch_config=data.get("software_patch_config", {}),
        disk_config=data.get("disk_config", {}),
        maintenance_config=data.get("maintenance_config", {}),
        scripts=data.get("scripts", []),
    )
    db.session.add(profile)
    db.session.commit()
    return jsonify(profile.to_dict()), 201


@automation_bp.route("/profiles/<profile_id>", methods=["GET"])
@jwt_required()
def get_profile(profile_id):
    err = _require_role("admin", "technician", "viewer")
    if err:
        return err
    profile = db.get_or_404(AutomationProfile, profile_id)
    return jsonify(profile.to_dict()), 200


@automation_bp.route("/profiles/<profile_id>", methods=["PUT"])
@jwt_required()
@validate_body(AutomationProfileUpdateSchema)
def update_profile(profile_id):
    err = _require_role("admin", "technician")
    if err:
        return err
    profile = db.get_or_404(AutomationProfile, profile_id)
    data = request.get_json(silent=True) or {}
    for field in ["name", "is_active", "schedule_type", "schedule_config",
                  "run_on_new_agents", "notification_emails", "os_patch_config",
                  "software_patch_config", "disk_config", "maintenance_config", "scripts"]:
        if field in data:
            setattr(profile, field, data[field])
    profile.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify(profile.to_dict()), 200


@automation_bp.route("/profiles/<profile_id>", methods=["DELETE"])
@jwt_required()
def delete_profile(profile_id):
    err = _require_role("admin")
    if err:
        return err
    profile = db.get_or_404(AutomationProfile, profile_id)
    db.session.delete(profile)
    db.session.commit()
    return jsonify({"message": "Profile deleted"}), 200


@automation_bp.route("/profiles/<profile_id>/run", methods=["POST"])
@jwt_required()
def run_profile_now(profile_id):
    err = _require_role("admin", "technician")
    if err:
        return err
    profile = db.get_or_404(AutomationProfile, profile_id)

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=30)
    recent = ScheduledTaskRun.query.filter(
        ScheduledTaskRun.profile_id == profile_id,
        ScheduledTaskRun.status == "queued",
        ScheduledTaskRun.started_at >= cutoff,
    ).first()
    if recent:
        return jsonify({"message": "Run already queued recently, skipping duplicate"}), 200

    from tasks.automation_tasks import enqueue_profile_run
    task = enqueue_profile_run.delay(profile_id)

    profile.last_run_at = datetime.now(timezone.utc)
    db.session.commit()

    return jsonify({
        "message": "Profile run enqueued",
        "celery_task_id": task.id,
    }), 202


@automation_bp.route("/runs", methods=["GET"])
@jwt_required()
def list_runs():
    err = _require_role("admin", "technician", "viewer")
    if err:
        return err
    profile_id = request.args.get("profile_id")

    query = ScheduledTaskRun.query
    if profile_id:
        query = query.filter_by(profile_id=profile_id)

    return paginated_response(query, lambda r: r.to_dict(), order_by=ScheduledTaskRun.started_at.desc())


@automation_bp.route("/runs/<run_id>", methods=["DELETE"])
@jwt_required()
def delete_run(run_id):
    err = _require_role("admin", "technician")
    if err:
        return err
    run = db.get_or_404(ScheduledTaskRun, run_id)
    db.session.delete(run)
    db.session.commit()
    return jsonify({"message": "Run deleted"}), 200


@automation_bp.route("/runs/clear-queued", methods=["DELETE"])
@jwt_required()
def clear_queued_runs():
    """Delete all QUEUED runs (bulk cleanup of duplicate entries)."""
    err = _require_role("admin", "technician")
    if err:
        return err
    profile_id = request.args.get("profile_id")
    query = ScheduledTaskRun.query.filter_by(status="queued")
    if profile_id:
        query = query.filter_by(profile_id=profile_id)
    count = query.count()
    query.delete(synchronize_session=False)
    db.session.commit()
    return jsonify({"message": f"Deleted {count} queued run(s)"}), 200
