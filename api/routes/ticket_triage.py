"""AI ticket triage — human approve/reject on staged (shadow-mode) suggestions,
and admin CRUD for the curated category whitelist."""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from extensions import db
from models.ticket import Ticket
from models.triage_category import TriageCategory
from models.audit import AuditLog
from utils.auth_decorators import require_role as _require_role
from services.ticket_triage_service import danger_scan, send_resolution_notification

ticket_triage_bp = Blueprint("ticket_triage", __name__)


@ticket_triage_bp.route("/<ticket_id>/triage/approve", methods=["POST"])
@jwt_required()
def approve_triage(ticket_id):
    err = _require_role("admin", "technician")
    if err:
        return err
    from services.ticket_service import update_ticket_service

    uid = get_jwt_identity()
    ticket = db.get_or_404(Ticket, ticket_id)
    if ticket.triage_status != "staged":
        return jsonify({"error": f"Ticket is not staged for approval (status: {ticket.triage_status})"}), 409

    data = request.get_json(silent=True) or {}
    reply = (data.get("reply_override") or ticket.ai_suggested_reply or "").strip()
    if not reply:
        return jsonify({"error": "No reply text available to send"}), 400
    if danger_scan(reply):
        return jsonify({"error": "This reply was flagged by the safety scan — edit it before sending"}), 400

    result, uerr = update_ticket_service(
        uid, get_jwt().get("role"), ticket,
        status="resolved", status_comment="Resolved — AI-drafted reply approved by staff.",
        skip_status_comment_requirement=True,
    )
    if uerr:
        return jsonify({"error": uerr[0]}), uerr[1]

    ticket.auto_resolved = True
    ticket.triage_status = "auto_resolved"
    ticket.ai_suggested_reply = reply
    db.session.add(AuditLog(
        user_id=uid, action="AI_TRIAGE_APPROVED", resource_type="ticket", resource_id=ticket.id,
        payload={"category": ticket.category, "edited": bool(data.get("reply_override"))},
    ))
    db.session.commit()

    cat_row = TriageCategory.query.filter_by(code=ticket.category, is_active=True).first()
    send_resolution_notification(ticket, reply, cat_row)

    return jsonify(ticket.to_dict()), 200


@ticket_triage_bp.route("/<ticket_id>/triage/reject", methods=["POST"])
@jwt_required()
def reject_triage(ticket_id):
    err = _require_role("admin", "technician")
    if err:
        return err
    uid = get_jwt_identity()
    ticket = db.get_or_404(Ticket, ticket_id)
    if ticket.triage_status != "staged":
        return jsonify({"error": f"Ticket is not staged for approval (status: {ticket.triage_status})"}), 409

    data = request.get_json(silent=True) or {}
    assignee_id = data.get("assignee_id")
    if assignee_id:
        ticket.assignee_id = assignee_id

    ticket.triage_status = "escalated"
    db.session.add(AuditLog(
        user_id=uid, action="AI_TRIAGE_REJECTED", resource_type="ticket", resource_id=ticket.id,
        payload={"category": ticket.category, "assignee_id": assignee_id},
    ))
    db.session.commit()

    return jsonify(ticket.to_dict()), 200


# ── Category whitelist config ──────────────────────────────────────────────────

_triage_categories_bp = Blueprint("triage_categories", __name__)


@_triage_categories_bp.route("/", methods=["GET"])
@jwt_required()
def list_categories():
    categories = TriageCategory.query.order_by(TriageCategory.label).all()
    return jsonify([c.to_dict() for c in categories]), 200


@_triage_categories_bp.route("/<category_id>", methods=["PUT"])
@jwt_required()
def update_category(category_id):
    err = _require_role("admin")
    if err:
        return err
    category = db.get_or_404(TriageCategory, category_id)
    data = request.get_json(silent=True) or {}

    if "auto_resolve_enabled" in data:
        category.auto_resolve_enabled = bool(data["auto_resolve_enabled"])
    if "shadow_mode" in data:
        category.shadow_mode = bool(data["shadow_mode"])
    if "is_active" in data:
        category.is_active = bool(data["is_active"])
    if "confidence_threshold" in data:
        v = data["confidence_threshold"]
        if not isinstance(v, (int, float)) or not (0 <= v <= 1):
            return jsonify({"error": "confidence_threshold must be a number between 0 and 1"}), 400
        category.confidence_threshold = float(v)
    if "auto_close_days" in data:
        v = data["auto_close_days"]
        if v is not None and (not isinstance(v, int) or v < 1):
            return jsonify({"error": "auto_close_days must be an integer >= 1, or null"}), 400
        category.auto_close_days = v

    db.session.add(AuditLog(
        user_id=get_jwt_identity(), action="UPDATE", resource_type="triage_category", resource_id=category.id,
        payload={
            "auto_resolve_enabled": category.auto_resolve_enabled, "shadow_mode": category.shadow_mode,
            "is_active": category.is_active, "confidence_threshold": category.confidence_threshold,
        },
    ))
    db.session.commit()
    return jsonify(category.to_dict()), 200
