import hashlib
import uuid
import secrets
from datetime import datetime, timezone, timedelta

_TOKEN_LIFETIME_DAYS = 90
_TOKEN_ROTATE_BEFORE_DAYS = 7  # issue new token when < 7 days remain

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import create_access_token

from extensions import db, limiter
from models.device import Device, DeviceMetrics, InstalledSoftware
from models.audit import AgentToken
from models.customer import Customer
from utils.validation import validate_body
from schemas.agents import (
    AgentRegisterSchema, AgentHeartbeatSchema, AgentTaskResultSchema,
    AgentSoftwareSchema, AgentPatchesSchema,
)

agents_bp = Blueprint("agents", __name__)

OFFLINE_THRESHOLD_SECONDS = 180  # 3 minutes without heartbeat = offline


def _get_device_by_token(device_id: str):
    """Validate agent token. Returns (device, agent_token) or (None, None)."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None, None
    token = auth[7:]
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    agent_token = AgentToken.query.filter_by(
        device_id=device_id,
        token_hash=token_hash,
        is_revoked=False,
    ).first()
    if not agent_token:
        return None, None

    now = datetime.now(timezone.utc)
    if agent_token.expires_at:
        # SQLite returns naive datetimes; treat as UTC
        exp = agent_token.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= now:
            return None, None  # expired — agent must re-register

    agent_token.last_used_at = now
    db.session.add(agent_token)
    return Device.query.get(device_id), agent_token


@agents_bp.route("/register", methods=["POST"])
@limiter.limit("10 per minute")
@validate_body(AgentRegisterSchema)
def register():
    """Agent first-time registration. Returns device_id + agent_token."""
    data = request.get_json(silent=True) or {}

    # Validate org registration token
    org_token = data.get("org_token", "")
    if not secrets.compare_digest(org_token, current_app.config["ORG_REGISTRATION_TOKEN"]):
        return jsonify({"error": "Invalid org token"}), 403

    # Find or create device by hardware fingerprint
    hostname = data.get("hostname", "").strip()
    mac_address = data.get("mac_address", "").strip()
    serial = data.get("serial_number", "").strip()

    if not hostname:
        return jsonify({"error": "hostname required"}), 400

    fingerprint = hashlib.sha256(
        f"{hostname}|{mac_address}|{serial}".encode("utf-8")
    ).hexdigest()

    # Check if device already registered by fingerprint
    existing = Device.query.filter_by(hardware_fingerprint=fingerprint).first()
    if existing:
        # Re-registration: revoke old tokens, issue new one
        AgentToken.query.filter_by(device_id=existing.id, is_revoked=False).update(
            {"is_revoked": True}
        )
        device = existing
    else:
        customer_id_hint = data.get("customer_id", "").strip()
        if customer_id_hint:
            customer = Customer.query.filter_by(id=customer_id_hint, is_active=True).first()
            if not customer:
                return jsonify({"error": "Invalid customer_id"}), 400
        else:
            customer = Customer.query.filter_by(is_active=True).first()
            if not customer:
                return jsonify({"error": "No active customer found. Create a customer first."}), 400

        device = Device(
            customer_id=customer.id,
            hostname=hostname,
            platform=data.get("platform", "windows"),
            hardware_fingerprint=fingerprint,
        )
        db.session.add(device)
        db.session.flush()  # Get device.id

    # Update device info from registration payload
    device.hostname = hostname
    device.os_name = data.get("os_name")
    device.os_version = data.get("os_version")
    device.os_build = data.get("os_build")
    device.architecture = data.get("architecture")
    device.cpu_model = data.get("cpu_model")
    device.cpu_cores = data.get("cpu_cores")
    device.ram_gb = data.get("ram_gb")
    device.serial_number = serial
    device.mac_address = mac_address
    device.ip_address = request.remote_addr
    device.agent_version = data.get("agent_version", "1.0.0")
    device.last_seen = datetime.now(timezone.utc)
    device.is_online = True
    device.status = "healthy"

    # Issue new agent token with expiry
    raw_token = str(uuid.uuid4()) + secrets.token_hex(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)

    agent_token = AgentToken(
        device_id=device.id,
        token_hash=token_hash,
        issued_at=now,
        expires_at=now + timedelta(days=_TOKEN_LIFETIME_DAYS),
    )
    db.session.add(agent_token)
    db.session.commit()

    return jsonify({
        "device_id": device.id,
        "agent_token": raw_token,
        "message": "Registered successfully",
    }), 201


@agents_bp.route("/<device_id>/heartbeat", methods=["POST"])
@validate_body(AgentHeartbeatSchema)
def heartbeat(device_id):
    """Receive metrics payload from agent. Updates device status."""
    device, agent_token = _get_device_by_token(device_id)
    if not device:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    now = datetime.now(timezone.utc)

    # Capture pre-update status for transition events
    _was_online = device.is_online

    # Update device online status
    device.last_seen = now
    device.is_online = True
    device.ip_address = request.remote_addr
    if data.get("agent_version"):
        device.agent_version = data["agent_version"]
    if not device.cpu_model and data.get("cpu_model"):
        device.cpu_model = data["cpu_model"]

    # Determine device status from metrics
    cpu = data.get("cpu_pct", 0)
    ram = data.get("ram_pct", 0)
    disk = data.get("disk_pct", 0)
    _prev_status = device.status
    if cpu > 90 or ram > 90 or disk > 90:
        device.status = "critical"
    elif cpu > 75 or ram > 75 or disk > 80:
        device.status = "warning"
    else:
        device.status = "healthy"

    # Store metrics snapshot
    metrics = DeviceMetrics(
        device_id=device.id,
        collected_at=now,
        cpu_pct=cpu,
        ram_pct=ram,
        ram_used_gb=data.get("ram_used_gb"),
        disk_pct=disk,
        disk_used_gb=data.get("disk_used_gb"),
        disk_total_gb=data.get("disk_total_gb"),
        network_bytes_sent=data.get("network_bytes_sent"),
        network_bytes_recv=data.get("network_bytes_recv"),
        battery_pct=data.get("battery_pct"),
        battery_plugged=data.get("battery_plugged"),
        uptime_seconds=data.get("uptime_seconds"),
        top_processes=data.get("top_processes"),
        disks=data.get("disks"),
    )
    db.session.add(metrics)

    # Rotate token when < 7 days remain (sliding window renewal)
    new_raw_token = None
    if agent_token and agent_token.expires_at:
        exp = agent_token.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        days_left = (exp - now).days
        if days_left < _TOKEN_ROTATE_BEFORE_DAYS:
            agent_token.is_revoked = True
            new_raw_token = str(uuid.uuid4()) + secrets.token_hex(32)
            new_hash = hashlib.sha256(new_raw_token.encode("utf-8")).hexdigest()
            db.session.add(AgentToken(
                device_id=device_id,
                token_hash=new_hash,
                issued_at=now,
                expires_at=now + timedelta(days=_TOKEN_LIFETIME_DAYS),
            ))

    # Auto-resolve open offline alerts when device comes back online
    if not _was_online:
        from models.alert import Alert, AlertRule
        offline_rule = AlertRule.query.filter_by(metric="offline", is_active=True).first()
        if offline_rule:
            Alert.query.filter(
                Alert.rule_id == offline_rule.id,
                Alert.device_id == device.id,
                Alert.status == "open",
            ).update({"status": "resolved", "resolved_at": now})

    db.session.commit()

    # Publish SSE events on state transitions (best-effort, never block heartbeat)
    try:
        from utils.events import publish_event
        if not _was_online:
            publish_event("device_online", {
                "device_id": device.id,
                "hostname": device.hostname,
                "status": device.status,
            })
        elif device.status != _prev_status:
            publish_event("device_status", {
                "device_id": device.id,
                "hostname": device.hostname,
                "status": device.status,
                "prev_status": _prev_status,
            })
    except Exception:
        pass

    resp = {"status": "ok", "server_time": now.isoformat()}
    if new_raw_token:
        resp["new_agent_token"] = new_raw_token
    return jsonify(resp), 200


@agents_bp.route("/<device_id>/tasks", methods=["GET"])
def get_tasks(device_id):
    """Return pending tasks for this device."""
    device, _ = _get_device_by_token(device_id)
    if not device:
        return jsonify({"error": "Unauthorized"}), 401

    # Import here to avoid circular imports
    from models.script import ScriptRun, Script
    from models.automation import ScheduledTaskRun

    tasks = []

    # Pending script runs
    pending_scripts = ScriptRun.query.filter_by(
        device_id=device_id, status="queued"
    ).all()
    # Batch-fetch all needed scripts in one query (eliminates N+1)
    script_ids = {run.script_id for run in pending_scripts}
    scripts_by_id = {}
    if script_ids:
        scripts_by_id = {
            s.id: s for s in Script.query.filter(Script.id.in_(script_ids)).all()
        }
    for run in pending_scripts:
        script = scripts_by_id.get(run.script_id)
        if script:
            tasks.append({
                "task_id": run.id,
                "type": "run_script",
                "payload": {
                    "script_id": script.id,
                    "file_type": script.file_type,
                    "content": script.content,
                    "timeout_seconds": run.timeout_seconds,
                },
            })
            run.status = "running"
            run.started_at = datetime.now(timezone.utc)

    db.session.commit()
    return jsonify({"tasks": tasks}), 200


@agents_bp.route("/<device_id>/task_result", methods=["POST"])
@validate_body(AgentTaskResultSchema)
def task_result(device_id):
    """Agent posts completed task result."""
    device, _ = _get_device_by_token(device_id)
    if not device:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id")
    task_type = data.get("type")

    if task_type == "run_script":
        from models.script import ScriptRun
        run = ScriptRun.query.get(task_id)
        if run and run.device_id == device_id:
            run.exit_code = data.get("exit_code")
            run.stdout = (data.get("stdout") or "")[:65536]  # 64KB cap
            run.stderr = (data.get("stderr") or "")[:65536]
            run.completed_at = datetime.now(timezone.utc)
            run.status = "success" if data.get("exit_code") == 0 else "failed"
            db.session.commit()

    return jsonify({"status": "ok"}), 200


@agents_bp.route("/<device_id>/patches", methods=["PUT"])
@validate_body(AgentPatchesSchema)
def update_patches(device_id):
    """Agent reports pending Windows Update patches."""
    device, _ = _get_device_by_token(device_id)
    if not device:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    patch_list = data.get("patches", [])

    from models.patch import PatchRecord

    # Fetch only names column — no object hydration
    existing_names = {
        row[0]
        for row in db.session.execute(
            db.select(PatchRecord.patch_name).where(
                PatchRecord.device_id == device_id,
                PatchRecord.status == "pending",
            )
        ).all()
    }

    new_patches = []
    for item in patch_list[:500]:
        name = (item.get("name") or "")[:500]
        if not name or name in existing_names:
            continue
        new_patches.append(PatchRecord(
            device_id=device_id,
            patch_name=name,
            kb_id=item.get("kb_id"),
            patch_type=item.get("patch_type", "feature"),
            source="wu",
        ))
        existing_names.add(name)

    if new_patches:
        db.session.bulk_save_objects(new_patches)
        db.session.commit()
    return jsonify({"status": "ok", "added": len(new_patches)}), 200


@agents_bp.route("/<device_id>/screenshot", methods=["POST"])
def upload_screenshot(device_id):
    """Agent POSTs raw JPEG bytes. Saved to disk; dashboard fetches via GET /devices/<id>/screenshot."""
    device, _ = _get_device_by_token(device_id)
    if not device:
        return jsonify({"error": "Unauthorized"}), 401

    if request.content_type not in ("image/jpeg", "image/png"):
        return jsonify({"error": "Content-Type must be image/jpeg or image/png"}), 400

    data = request.get_data()
    if not data or len(data) < 100:
        return jsonify({"error": "Empty or too-small payload"}), 400
    if len(data) > 5 * 1024 * 1024:  # 5 MB cap
        return jsonify({"error": "Screenshot exceeds 5 MB limit"}), 413

    from pathlib import Path
    screenshots_dir = Path(__file__).parent.parent / "screenshots"
    screenshots_dir.mkdir(exist_ok=True)
    ext = "png" if request.content_type == "image/png" else "jpg"
    path = screenshots_dir / f"{device_id}.{ext}"
    # Remove opposite-extension file if it exists
    for old_ext in ("jpg", "png"):
        old = screenshots_dir / f"{device_id}.{old_ext}"
        if old != path and old.exists():
            old.unlink(missing_ok=True)
    path.write_bytes(data)
    return jsonify({"status": "ok", "bytes": len(data)}), 200


@agents_bp.route("/<device_id>/software", methods=["PUT"])
@validate_body(AgentSoftwareSchema)
def update_software(device_id):
    """Agent posts full installed software list (replaces previous)."""
    device, _ = _get_device_by_token(device_id)
    if not device:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    software_list = data.get("software", [])

    # Delete old entries and bulk-replace
    InstalledSoftware.query.filter_by(device_id=device_id).delete()
    now = datetime.now(timezone.utc)
    objects = [
        InstalledSoftware(
            device_id=device_id,
            name=str(item.get("name", ""))[:500],
            version=str(item.get("version", ""))[:255] if item.get("version") else None,
            publisher=str(item.get("publisher", ""))[:255] if item.get("publisher") else None,
            install_date=item.get("install_date"),
            source=item.get("source", "registry"),
            last_seen=now,
        )
        for item in software_list[:2000]
    ]
    if objects:
        db.session.bulk_save_objects(objects)
    db.session.commit()
    return jsonify({"status": "ok", "count": len(software_list)}), 200
