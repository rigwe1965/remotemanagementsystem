"""
IoT sensor data ingestion and query.
POST /api/sensors/<device_id>/data  — HTTP push from agents/gateways
GET  /api/sensors/<device_id>/data  — query time-series readings
GET  /api/sensors/summary           — per-customer sensor device counts
"""
import hashlib
import logging
from datetime import datetime, timezone, timedelta

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt

from extensions import db, limiter
from models.device import Device, DeviceSensorReading, SENSOR_TYPES
from models.audit import AgentToken

sensors_bp = Blueprint("sensors", __name__)
logger = logging.getLogger(__name__)

_MAX_BATCH = 100
_MAX_HOURS = 168  # 7 days


def _get_device_by_token(device_id: str):
    """Validate agent Bearer token. Returns device or None."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    agent_token = AgentToken.query.filter_by(
        device_id=device_id,
        token_hash=token_hash,
        is_revoked=False,
    ).first()
    if not agent_token:
        return None
    now = datetime.now(timezone.utc)
    if agent_token.expires_at:
        exp = agent_token.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= now:
            return None
    agent_token.last_used_at = now
    db.session.add(agent_token)
    return db.session.get(Device, device_id)


def _require_role(*roles):
    claims = get_jwt()
    if claims.get("role") == "superadmin":
        return None
    if claims.get("role") not in roles:
        return jsonify({"error": "Insufficient permissions"}), 403
    return None


@sensors_bp.route("/<device_id>/data", methods=["POST"])
@limiter.limit("60 per minute")
def push_sensor_data(device_id: str):
    """HTTP push endpoint — called by iot_agent.py or any gateway."""
    device = _get_device_by_token(device_id)
    if not device:
        return jsonify({"error": "Unauthorized or expired token"}), 401

    body = request.get_json(silent=True)
    if not body or not isinstance(body, list):
        return jsonify({"error": "Expected JSON array of readings"}), 400

    if len(body) > _MAX_BATCH:
        return jsonify({"error": f"Max {_MAX_BATCH} readings per request"}), 400

    now = datetime.now(timezone.utc)
    inserted = 0
    errors = []

    for i, r in enumerate(body):
        sensor_type = r.get("sensor_type", "")
        if sensor_type not in SENSOR_TYPES:
            errors.append(f"[{i}] unknown sensor_type '{sensor_type}'")
            continue
        try:
            value = float(r["value"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"[{i}] missing or invalid 'value'")
            continue

        raw_ts = r.get("collected_at")
        try:
            if raw_ts:
                collected_at = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                if collected_at.tzinfo is None:
                    collected_at = collected_at.replace(tzinfo=timezone.utc)
            else:
                collected_at = now
        except (ValueError, AttributeError):
            collected_at = now

        reading = DeviceSensorReading(
            device_id=device_id,
            customer_id=device.customer_id,
            collected_at=collected_at,
            sensor_type=sensor_type,
            value=value,
            unit=r.get("unit"),
            channel=r.get("channel"),
            source="http_push",
        )
        db.session.add(reading)
        inserted += 1

    if inserted:
        db.session.commit()
        try:
            from utils.events import publish_event
            publish_event("sensor_reading", {
                "device_id": device_id,
                "hostname": device.hostname,
                "count": inserted,
            })
        except Exception:
            pass

    resp = {"inserted": inserted}
    if errors:
        resp["errors"] = errors
    return jsonify(resp), 200 if inserted else 400


@sensors_bp.route("/<device_id>/data", methods=["GET"])
@jwt_required()
def get_sensor_data(device_id: str):
    """Query sensor readings for a device."""
    err = _require_role("admin", "technician", "viewer", "client")
    if err:
        return err

    # Client role: enforce customer isolation
    claims = get_jwt()
    if claims.get("role") == "client":
        device = db.get_or_404(Device, device_id)
        if device.customer_id != claims.get("customer_id"):
            return jsonify({"error": "Forbidden"}), 403

    sensor_type = request.args.get("sensor_type")
    hours = min(int(request.args.get("hours", 24)), _MAX_HOURS)
    limit = min(int(request.args.get("limit", 5000)), 5000)
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    q = DeviceSensorReading.query.filter(
        DeviceSensorReading.device_id == device_id,
        DeviceSensorReading.collected_at >= since,
    )
    if sensor_type:
        q = q.filter(DeviceSensorReading.sensor_type == sensor_type)

    readings = q.order_by(DeviceSensorReading.collected_at.asc()).limit(limit).all()
    return jsonify([r.to_dict() for r in readings]), 200


@sensors_bp.route("/summary", methods=["GET"])
@jwt_required()
def sensor_summary():
    """Count of devices with sensor data in last 24h, grouped by customer."""
    err = _require_role("admin", "technician", "superadmin")
    if err:
        return err

    from sqlalchemy import func
    since = datetime.now(timezone.utc) - timedelta(hours=24)

    rows = (
        db.session.query(
            DeviceSensorReading.customer_id,
            func.count(DeviceSensorReading.device_id.distinct()).label("device_count"),
            func.count(DeviceSensorReading.id).label("reading_count"),
        )
        .filter(DeviceSensorReading.collected_at >= since)
        .group_by(DeviceSensorReading.customer_id)
        .all()
    )

    return jsonify([
        {"customer_id": r.customer_id, "device_count": r.device_count, "reading_count": r.reading_count}
        for r in rows
    ]), 200
