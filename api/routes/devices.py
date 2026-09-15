import json
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import jwt_required, get_jwt
from sqlalchemy import func
from extensions import db, limiter
from models.device import Device, DeviceMetrics
from utils.validation import validate_body
from utils.cache import cache_get_raw, cache_set_raw, cache_delete_pattern
from schemas.devices import DeviceUpdateSchema, QueueTaskSchema, DeployPatchesSchema

devices_bp = Blueprint("devices", __name__)


def _batch_latest_metrics(device_ids: list) -> dict:
    """Return {device_id: metrics_dict} for a list of device IDs. 1 query."""
    if not device_ids:
        return {}
    subq = (
        db.select(func.max(DeviceMetrics.id).label("max_id"))
        .where(DeviceMetrics.device_id.in_(device_ids))
        .group_by(DeviceMetrics.device_id)
        .subquery()
    )
    rows = db.session.execute(
        db.select(DeviceMetrics).join(subq, DeviceMetrics.id == subq.c.max_id)
    ).scalars().all()
    return {m.device_id: m.to_dict() for m in rows}


def _require_role(*roles):
    claims = get_jwt()
    if claims.get("role") == "superadmin":
        return None  # superadmin bypasses all role checks
    if claims.get("role") not in roles:
        return jsonify({"error": "Insufficient permissions"}), 403
    return None


@devices_bp.route("/", methods=["GET"])
@jwt_required()
def list_devices():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 200)
    customer_id = request.args.get("customer_id")
    group_id = request.args.get("group_id")
    status = request.args.get("status")
    is_online = request.args.get("is_online")
    q = request.args.get("q", "")
    platform_filter = request.args.get("platform")
    is_agentless = request.args.get("is_agentless")
    device_type = request.args.get("device_type")

    _ck = (f"rmm:devices:list:p{page}:pp{per_page}:c{customer_id or ''}:"
           f"g{group_id or ''}:s{status or ''}:o{is_online or ''}:"
           f"pf{platform_filter or ''}:ia{is_agentless or ''}:dt{device_type or ''}:q{q}")
    raw = cache_get_raw(_ck)
    if raw:
        return Response(raw, mimetype="application/json")

    query = Device.query
    if customer_id:
        query = query.filter_by(customer_id=customer_id)
    if group_id:
        query = query.filter_by(group_id=group_id)
    if status:
        query = query.filter_by(status=status)
    if is_online is not None:
        query = query.filter_by(is_online=is_online.lower() == "true")
    if platform_filter:
        query = query.filter_by(platform=platform_filter)
    if is_agentless is not None:
        query = query.filter_by(is_agentless=is_agentless.lower() == "true")
    if device_type:
        query = query.filter_by(device_type=device_type)
    if q:
        query = query.filter(Device.hostname.ilike(f"%{q}%"))

    paginated = query.order_by(Device.hostname).paginate(page=page, per_page=per_page)
    metrics_by_device = _batch_latest_metrics([d.id for d in paginated.items])
    result = {
        "items": [
            d.to_dict(include_latest_metrics=True, latest_metrics_data=metrics_by_device.get(d.id))
            for d in paginated.items
        ],
        "total": paginated.total,
        "page": page,
        "pages": paginated.pages,
    }
    raw_json = json.dumps(result, default=str)
    cache_set_raw(_ck, raw_json, 30)
    return Response(raw_json, mimetype="application/json")


@devices_bp.route("/platform_counts", methods=["GET"])
@jwt_required()
def platform_counts():
    from utils.cache import cache_get, cache_set
    _CACHE_KEY = "rmm:dash:platform_counts"
    cached = cache_get(_CACHE_KEY)
    if cached:
        return jsonify(cached), 200

    rows = db.session.execute(
        db.select(Device.platform, Device.is_agentless, func.count(Device.id))
        .group_by(Device.platform, Device.is_agentless)
    ).all()
    by_platform = {}
    agentless_count = 0
    for platform, is_agentless, count in rows:
        if platform:
            by_platform[platform] = by_platform.get(platform, 0) + count
        if is_agentless:
            agentless_count += count
    result = {"by_platform": by_platform, "agentless": agentless_count}
    cache_set(_CACHE_KEY, result, 60)
    return jsonify(result), 200


@devices_bp.route("/<device_id>", methods=["GET"])
@jwt_required()
def get_device(device_id):
    device = db.get_or_404(Device, device_id)
    return jsonify(device.to_dict(include_latest_metrics=True)), 200


@devices_bp.route("/<device_id>", methods=["PUT"])
@jwt_required()
@validate_body(DeviceUpdateSchema)
def update_device(device_id):
    err = _require_role("admin", "technician")
    if err:
        return err
    device = db.get_or_404(Device, device_id)
    data = request.get_json(silent=True) or {}
    for field in ["display_name", "group_id", "customer_id",
                  "hostname", "platform", "device_type", "vendor"]:
        if field in data:
            setattr(device, field, data[field])
    db.session.commit()
    cache_delete_pattern("rmm:devices:list:*")
    return jsonify(device.to_dict()), 200


@devices_bp.route("/<device_id>", methods=["DELETE"])
@jwt_required()
def delete_device(device_id):
    err = _require_role("admin")
    if err:
        return err
    device = db.get_or_404(Device, device_id)
    db.session.delete(device)
    db.session.commit()
    cache_delete_pattern("rmm:devices:list:*")
    return jsonify({"message": "Device removed"}), 200


@devices_bp.route("/<device_id>/metrics", methods=["GET"])
@jwt_required()
def device_metrics(device_id):
    db.get_or_404(Device, device_id)
    hours = request.args.get("hours", 24, type=int)
    since = datetime.now(timezone.utc) - timedelta(hours=min(hours, 168))

    metrics = DeviceMetrics.query.filter(
        DeviceMetrics.device_id == device_id,
        DeviceMetrics.collected_at >= since,
    ).order_by(DeviceMetrics.collected_at).limit(5000).all()

    return jsonify([m.to_dict() for m in metrics]), 200


@devices_bp.route("/<device_id>/software", methods=["GET"])
@jwt_required()
def device_software(device_id):
    db.get_or_404(Device, device_id)
    from models.device import InstalledSoftware
    q = request.args.get("q", "")
    query = InstalledSoftware.query.filter_by(device_id=device_id)
    if q:
        query = query.filter(InstalledSoftware.name.ilike(f"%{q}%"))
    software = query.order_by(InstalledSoftware.name).all()
    return jsonify([s.to_dict() for s in software]), 200


@devices_bp.route("/<device_id>/reboot", methods=["POST"])
@jwt_required()
@limiter.limit("2 per minute")
def reboot_device(device_id):
    err = _require_role("admin", "technician")
    if err:
        return err
    device = db.get_or_404(Device, device_id)
    if not device.is_online:
        return jsonify({"error": "Device is offline"}), 400
    run_id = _queue_builtin_task(device_id, "reboot")
    return jsonify({"message": "Reboot queued", "device_id": device_id, "run_id": run_id}), 202


@devices_bp.route("/<device_id>/shutdown", methods=["POST"])
@jwt_required()
@limiter.limit("2 per minute")
def shutdown_device(device_id):
    err = _require_role("admin", "technician")
    if err:
        return err
    device = db.get_or_404(Device, device_id)
    if not device.is_online:
        return jsonify({"error": "Device is offline"}), 400
    run_id = _queue_builtin_task(device_id, "shutdown")
    return jsonify({"message": "Shutdown queued", "device_id": device_id, "run_id": run_id}), 202


@devices_bp.route("/<device_id>/queue_task", methods=["POST"])
@jwt_required()
@limiter.limit("5 per minute")
@validate_body(QueueTaskSchema)
def queue_device_task(device_id):
    """Queue a built-in maintenance task for a device. Agent picks it up on next poll."""
    err = _require_role("admin", "technician")
    if err:
        return err
    db.get_or_404(Device, device_id)
    data = request.get_json(silent=True) or {}
    task_type = (data.get("task_type") or "").strip()
    if not task_type:
        return jsonify({"error": "task_type required"}), 400

    from utils.builtin_scripts import get_builtin_script_id, TASK_TYPE_TO_TAG
    if task_type not in TASK_TYPE_TO_TAG:
        return jsonify({"error": f"Unknown task_type '{task_type}'. Valid: {list(TASK_TYPE_TO_TAG)}"}), 400

    run_id = _queue_builtin_task(device_id, task_type, timeout=data.get("timeout_seconds", 300))
    if not run_id:
        return jsonify({"error": "Built-in script not found. Restart API to re-sync."}), 500

    return jsonify({"run_id": run_id, "task_type": task_type, "status": "queued"}), 202


@devices_bp.route("/<device_id>/deploy_patches", methods=["POST"])
@jwt_required()
@limiter.limit("2 per minute")
@validate_body(DeployPatchesSchema)
def deploy_patches_route(device_id):
    """Trigger Celery task to deploy approved patches to a device."""
    err = _require_role("admin", "technician")
    if err:
        return err
    db.get_or_404(Device, device_id)
    data = request.get_json(silent=True) or {}
    patch_ids = data.get("patch_ids", [])
    if not patch_ids:
        return jsonify({"error": "patch_ids required"}), 400
    from tasks.patch_tasks import deploy_patches
    deploy_patches.delay(device_id, patch_ids)
    return jsonify({"message": "Patch deployment queued", "count": len(patch_ids)}), 202


@devices_bp.route("/<device_id>/ping_check", methods=["POST"])
@jwt_required()
def ping_check(device_id):
    """Immediately ping an agentless device and update its online status."""
    device = db.get_or_404(Device, device_id)
    if not device.is_agentless or not device.ip_address:
        return jsonify({"error": "Only available for agentless devices with an IP"}), 400
    from tasks.network_tasks import _ping_host
    alive = _ping_host(device.ip_address)
    now = datetime.now(timezone.utc)
    device.is_online = alive
    if alive:
        device.last_seen = now
    db.session.commit()
    return jsonify({"is_online": alive, "checked_at": now.isoformat()}), 200


@devices_bp.route("/<device_id>/screenshot", methods=["GET"])
@jwt_required()
def get_screenshot(device_id):
    """Return latest screenshot for a device as JPEG/PNG, or 404 if none captured yet."""
    db.get_or_404(Device, device_id)
    from pathlib import Path
    from flask import send_file
    screenshots_dir = Path(__file__).parent.parent / "screenshots"
    for ext in ("jpg", "png"):
        path = screenshots_dir / f"{device_id}.{ext}"
        if path.exists():
            mimetype = "image/jpeg" if ext == "jpg" else "image/png"
            return send_file(str(path), mimetype=mimetype)
    return jsonify({"error": "No screenshot available for this device"}), 404


def _queue_builtin_task(device_id: str, task_type: str, timeout: int = 300):
    """Create a ScriptRun for a built-in task. Returns run_id or None."""
    from models.script import ScriptRun
    from utils.builtin_scripts import get_builtin_script_id
    from flask_jwt_extended import get_jwt_identity

    script_id = get_builtin_script_id(task_type)
    if not script_id:
        return None
    try:
        uid = get_jwt_identity()
    except Exception:
        uid = None

    run = ScriptRun(
        script_id=script_id,
        device_id=device_id,
        triggered_by=uid,
        timeout_seconds=timeout,
    )
    db.session.add(run)
    db.session.commit()
    return run.id
