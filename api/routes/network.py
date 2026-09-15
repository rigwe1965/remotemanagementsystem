import threading
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from extensions import db
from models.audit import NetworkScan
from utils.validation import validate_body
from schemas.network import NetworkScanSchema, AgentlessDevicesSchema

network_bp = Blueprint("network", __name__)


def _require_role(*roles):
    claims = get_jwt()
    if claims.get("role") == "superadmin":
        return None
    if claims.get("role") not in roles:
        return jsonify({"error": "Insufficient permissions"}), 403
    return None


@network_bp.route("/scan", methods=["POST"])
@jwt_required()
@validate_body(NetworkScanSchema)
def trigger_scan():
    err = _require_role("admin", "technician")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if not data.get("scan_range"):
        return jsonify({"error": "scan_range required"}), 400

    scan = NetworkScan(
        customer_id=data.get("customer_id") or None,
        initiated_by=get_jwt_identity(),
        scan_range=data["scan_range"],
        status="running",
    )
    db.session.add(scan)
    db.session.commit()

    app = current_app._get_current_object()
    scan_id = scan.id

    def _run():
        from tasks.network_tasks import _run_scan
        with app.app_context():
            _run_scan(scan_id)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"message": "Scan started", "scan_id": scan_id}), 202


@network_bp.route("/agentless_devices", methods=["POST"])
@jwt_required()
@validate_body(AgentlessDevicesSchema)
def upsert_agentless_devices():
    """Persist a batch of discovered hosts as agentless Device records."""
    err = _require_role("admin", "technician")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    hosts = data.get("hosts", [])
    customer_id = data.get("customer_id") or None
    if not hosts:
        return jsonify({"error": "hosts list required"}), 400

    from tasks.network_tasks import _upsert_agentless_host
    created = updated = skipped = 0
    for h in hosts:
        result = _upsert_agentless_host(
            ip=h.get("ip", ""),
            mac=h.get("mac"),
            vendor=h.get("vendor", "Unknown"),
            platform=h.get("platform", "unknown"),
            device_type=h.get("device_type", "unknown"),
            customer_id=customer_id,
        )
        if result == "created":
            created += 1
        elif result == "updated":
            updated += 1
        else:
            skipped += 1

    return jsonify({"created": created, "updated": updated, "skipped": skipped}), 200


@network_bp.route("/scans", methods=["GET"])
@jwt_required()
def list_scans():
    err = _require_role("admin", "technician", "viewer")
    if err:
        return err
    customer_id = request.args.get("customer_id")
    query = NetworkScan.query
    if customer_id:
        query = query.filter_by(customer_id=customer_id)
    scans = query.order_by(NetworkScan.started_at.desc()).limit(50).all()
    return jsonify([s.to_dict() for s in scans]), 200


@network_bp.route("/scans/<scan_id>", methods=["GET"])
@jwt_required()
def get_scan(scan_id):
    err = _require_role("admin", "technician", "viewer")
    if err:
        return err
    scan = db.get_or_404(NetworkScan, scan_id)
    return jsonify({
        **scan.to_dict(),
        "discovered_hosts": scan.discovered_hosts,
    }), 200
