"""PSA integration routes — ConnectWise Manage + Autotask."""
import logging
from datetime import datetime, timezone, timedelta

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt

from extensions import db
from models.psa_integration import PsaIntegration, PsaCompanyMap, PsaTicketMap, encrypt_cred

logger = logging.getLogger(__name__)
psa_bp = Blueprint("psa", __name__)

VALID_TYPES = {"connectwise", "autotask"}


def _require_role(*roles):
    claims = get_jwt()
    if claims.get("role") == "superadmin":
        return None
    if claims.get("role") not in roles:
        return jsonify({"error": "Insufficient permissions"}), 403
    return None


# ─── Integration CRUD ──────────────────────────────────────────────────────────

@psa_bp.route("/integrations", methods=["GET"])
@jwt_required()
def list_integrations():
    err = _require_role("admin", "technician")
    if err:
        return err
    integrations = PsaIntegration.query.order_by(PsaIntegration.created_at.desc()).all()
    return jsonify([i.to_dict() for i in integrations]), 200


@psa_bp.route("/integrations", methods=["POST"])
@jwt_required()
def create_integration():
    err = _require_role("admin")
    if err:
        return err
    data = request.get_json(silent=True) or {}

    psa_type = data.get("type", "").lower()
    if psa_type not in VALID_TYPES:
        return jsonify({"error": f"type must be one of: {sorted(VALID_TYPES)}"}), 400

    required = ["name", "api_url", "client_id", "client_secret"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    if psa_type == "connectwise" and not data.get("company_id"):
        return jsonify({"error": "company_id required for ConnectWise"}), 400

    integration = PsaIntegration(
        name=data["name"],
        type=psa_type,
        api_url=data["api_url"].rstrip("/"),
        company_id=data.get("company_id"),
        client_id=data["client_id"],
        client_secret_enc=encrypt_cred(data["client_secret"]),
        site_name=data.get("site_name"),          # AT: username
        sync_tickets=data.get("sync_tickets", True),
        sync_companies=data.get("sync_companies", True),
        sync_configs=data.get("sync_configs", False),
        is_active=data.get("is_active", True),
    )
    db.session.add(integration)
    db.session.commit()
    return jsonify(integration.to_dict()), 201


@psa_bp.route("/integrations/<integration_id>", methods=["PUT"])
@jwt_required()
def update_integration(integration_id):
    err = _require_role("admin")
    if err:
        return err
    integration = db.get_or_404(PsaIntegration, integration_id)
    data = request.get_json(silent=True) or {}

    for field in ("name", "api_url", "company_id", "client_id", "site_name"):
        if field in data:
            setattr(integration, field, data[field])
    if data.get("client_secret"):
        integration.client_secret_enc = encrypt_cred(data["client_secret"])
    for bool_field in ("sync_tickets", "sync_companies", "sync_configs", "is_active"):
        if bool_field in data:
            setattr(integration, bool_field, bool(data[bool_field]))

    db.session.commit()
    return jsonify(integration.to_dict()), 200


@psa_bp.route("/integrations/<integration_id>", methods=["DELETE"])
@jwt_required()
def delete_integration(integration_id):
    err = _require_role("admin")
    if err:
        return err
    integration = db.get_or_404(PsaIntegration, integration_id)
    db.session.delete(integration)
    db.session.commit()
    return jsonify({"message": "Integration deleted"}), 200


# ─── Test connection ───────────────────────────────────────────────────────────

@psa_bp.route("/integrations/<integration_id>/test", methods=["POST"])
@jwt_required()
def test_connection(integration_id):
    err = _require_role("admin", "technician")
    if err:
        return err
    integration = db.get_or_404(PsaIntegration, integration_id)
    try:
        client = integration.get_client()
        success, message = client.test_connection()
    except Exception as exc:
        success, message = False, str(exc)

    if not success:
        integration.sync_error = f"Connection test failed: {message}"
        db.session.commit()
    return jsonify({"success": success, "message": message}), 200 if success else 502


# ─── Manual sync trigger ───────────────────────────────────────────────────────

@psa_bp.route("/integrations/<integration_id>/sync", methods=["POST"])
@jwt_required()
def trigger_sync(integration_id):
    err = _require_role("admin", "technician")
    if err:
        return err
    integration = db.get_or_404(PsaIntegration, integration_id)
    if not integration.is_active:
        return jsonify({"error": "Integration is disabled"}), 400
    try:
        from tasks.psa_tasks import sync_psa_integration
        sync_psa_integration.delay(integration_id)
        return jsonify({"message": "Sync queued", "integration_id": integration_id}), 202
    except Exception as exc:
        logger.error("Failed to queue PSA sync: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ─── Status / stats ───────────────────────────────────────────────────────────

@psa_bp.route("/integrations/<integration_id>/status", methods=["GET"])
@jwt_required()
def integration_status(integration_id):
    err = _require_role("admin", "technician")
    if err:
        return err
    integration = db.get_or_404(PsaIntegration, integration_id)
    ticket_count = PsaTicketMap.query.filter_by(psa_integration_id=integration_id).count()
    company_count = PsaCompanyMap.query.filter_by(psa_integration_id=integration_id).count()
    return jsonify({
        **integration.to_dict(),
        "stats": {
            "tickets_synced": ticket_count,
            "companies_mapped": company_count,
        },
    }), 200


# ─── Company map CRUD ─────────────────────────────────────────────────────────

@psa_bp.route("/integrations/<integration_id>/company-maps", methods=["GET"])
@jwt_required()
def list_company_maps(integration_id):
    err = _require_role("admin", "technician")
    if err:
        return err
    db.get_or_404(PsaIntegration, integration_id)
    maps = PsaCompanyMap.query.filter_by(psa_integration_id=integration_id).all()
    return jsonify([m.to_dict() for m in maps]), 200


@psa_bp.route("/integrations/<integration_id>/company-maps", methods=["POST"])
@jwt_required()
def create_company_map(integration_id):
    err = _require_role("admin")
    if err:
        return err
    db.get_or_404(PsaIntegration, integration_id)
    data = request.get_json(silent=True) or {}
    if not data.get("customer_id") or not data.get("psa_company_id"):
        return jsonify({"error": "customer_id and psa_company_id required"}), 400

    existing = PsaCompanyMap.query.filter_by(
        psa_integration_id=integration_id,
        customer_id=data["customer_id"],
    ).first()
    if existing:
        existing.psa_company_id = data["psa_company_id"]
        existing.psa_company_name = data.get("psa_company_name")
        existing.synced_at = datetime.now(timezone.utc)
        db.session.commit()
        return jsonify(existing.to_dict()), 200

    mapping = PsaCompanyMap(
        psa_integration_id=integration_id,
        customer_id=data["customer_id"],
        psa_company_id=data["psa_company_id"],
        psa_company_name=data.get("psa_company_name"),
    )
    db.session.add(mapping)
    db.session.commit()
    return jsonify(mapping.to_dict()), 201


@psa_bp.route("/integrations/<integration_id>/company-maps/<map_id>", methods=["DELETE"])
@jwt_required()
def delete_company_map(integration_id, map_id):
    err = _require_role("admin")
    if err:
        return err
    mapping = PsaCompanyMap.query.filter_by(
        id=map_id, psa_integration_id=integration_id
    ).first_or_404()
    db.session.delete(mapping)
    db.session.commit()
    return jsonify({"message": "Company map removed"}), 200


# ─── PSA company discovery ────────────────────────────────────────────────────

@psa_bp.route("/integrations/<integration_id>/psa-companies", methods=["GET"])
@jwt_required()
def fetch_psa_companies(integration_id):
    """Fetch live company list from the PSA for use in the mapping UI."""
    err = _require_role("admin", "technician")
    if err:
        return err
    integration = db.get_or_404(PsaIntegration, integration_id)
    try:
        client = integration.get_client()
        companies = client.get_companies()
        return jsonify(companies), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502
