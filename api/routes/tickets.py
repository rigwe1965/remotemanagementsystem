from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from extensions import db
from models.ticket import Ticket, TicketComment
from models.user import User
from models.customer import Customer
from models.audit import AuditLog
from utils.validation import validate_body
from schemas.tickets import TicketCreateSchema, TicketUpdateSchema, CommentCreateSchema
from utils.notifications import (
    send_ticket_created_client,
    send_ticket_assigned,
    send_ticket_resolved_client,
    send_ticket_comment_to_client,
    send_ticket_comment_to_assignee,
)

tickets_bp = Blueprint("tickets", __name__)


def _require_role(*roles):
    claims = get_jwt()
    if claims.get("role") == "superadmin":
        return None
    if claims.get("role") not in roles:
        return jsonify({"error": "Insufficient permissions"}), 403
    return None


_SLA_HOURS = {"critical": 4, "high": 8, "medium": 24, "low": 72}
_sla_cache: dict = {}  # {(customer_id, priority): (hours, expires_at)}
_SLA_CACHE_TTL = 120  # seconds


def _sla_resolution_hours(priority: str, customer_id: str) -> int:
    """Look up SLA resolution hours: customer-specific policy first, then global, then hardcoded.
    Results cached in-process for 120s to avoid 2 DB queries per ticket creation."""
    import time
    from models.sla_policy import SLAPolicy

    key = (customer_id, priority)
    entry = _sla_cache.get(key)
    if entry and entry[1] > time.monotonic():
        return entry[0]

    hours = None
    if customer_id:
        policy = SLAPolicy.query.filter_by(customer_id=customer_id, priority=priority).first()
        if policy:
            hours = policy.resolution_hours
    if hours is None:
        global_policy = SLAPolicy.query.filter_by(customer_id=None, priority=priority).first()
        if global_policy:
            hours = global_policy.resolution_hours
    if hours is None:
        hours = _SLA_HOURS.get(priority, 24)

    _sla_cache[key] = (hours, time.monotonic() + _SLA_CACHE_TTL)
    return hours


def _current_claims():
    return get_jwt()


def _get_client_emails(customer_id: str) -> list:
    """Return emails of active client-role users linked to this customer."""
    clients = User.query.filter_by(role="client", customer_id=customer_id, is_active=True).all()
    return [u.email for u in clients if u.email]


def _customer_name(customer_id: str) -> str:
    c = db.session.get(Customer, customer_id)
    return c.name if c else "Unknown"


def _ticket_audit(action: str, user_id: str, ticket_id: str, payload: dict = None):
    log = AuditLog(
        user_id=user_id,
        action=action,
        resource_type="ticket",
        resource_id=ticket_id,
        ip_address=request.remote_addr,
        user_agent=request.headers.get("User-Agent", "")[:500],
        payload=payload,
    )
    db.session.add(log)


@tickets_bp.route("/", methods=["GET"])
@jwt_required()
def list_tickets():
    claims = _current_claims()
    role = claims.get("role")
    uid = get_jwt_identity()

    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 200)
    status = request.args.get("status")
    priority = request.args.get("priority")
    customer_id = request.args.get("customer_id")
    assignee_id = request.args.get("assignee_id")
    department_id = request.args.get("department_id")

    query = Ticket.query

    # Client users see only their own customer's tickets
    if role == "client":
        user = db.session.get(User, uid)
        if not user or not user.customer_id:
            return jsonify({"items": [], "total": 0, "page": page}), 200
        query = query.filter_by(customer_id=user.customer_id)
    else:
        if customer_id:
            query = query.filter_by(customer_id=customer_id)

    if status:
        query = query.filter_by(status=status)
    if priority:
        query = query.filter_by(priority=priority)
    if assignee_id:
        query = query.filter_by(assignee_id=assignee_id)
    if department_id:
        query = query.filter_by(department_id=department_id)

    paginated = query.order_by(Ticket.created_at.desc()).paginate(page=page, per_page=per_page)
    return jsonify({
        "items": [t.to_dict() for t in paginated.items],
        "total": paginated.total,
        "page": page,
    }), 200


@tickets_bp.route("/", methods=["POST"])
@jwt_required()
@validate_body(TicketCreateSchema)
def create_ticket():
    claims = _current_claims()
    role = claims.get("role")
    uid = get_jwt_identity()

    # Client and staff roles can create tickets; viewers cannot
    if role not in ("admin", "technician", "client", "superadmin"):
        return jsonify({"error": "Insufficient permissions"}), 403

    data = request.get_json(silent=True) or {}

    if role == "client":
        # Auto-populate from client's account; ignore any customer_id in payload
        user = db.session.get(User, uid)
        if not user or not user.customer_id:
            return jsonify({"error": "Client account not linked to a customer"}), 400
        customer_id = user.customer_id
        source = "client"
        dept_id = current_app.config.get("HELPDESK_DEPT_ID")
    else:
        customer_id = data.get("customer_id")
        if not customer_id:
            return jsonify({"error": "customer_id required"}), 400
        source = data.get("source", "manual")
        dept_id = data.get("department_id")

    if not data.get("title"):
        return jsonify({"error": "title required"}), 400

    priority = data.get("priority", "medium")
    due_date = data.get("due_date") or (
        datetime.now(timezone.utc) + timedelta(hours=_sla_resolution_hours(priority, customer_id))
    )
    ticket = Ticket(
        title=data["title"],
        description=data.get("description"),
        customer_id=customer_id,
        device_id=data.get("device_id"),
        assignee_id=data.get("assignee_id"),
        priority=priority,
        status=data.get("status", "open"),
        source=source,
        alert_id=data.get("alert_id"),
        department_id=dept_id,
        due_date=due_date,
        tags=data.get("tags", []),
    )
    db.session.add(ticket)
    _ticket_audit("CREATE", uid, ticket.id, {"title": ticket.title, "priority": ticket.priority, "source": source})
    db.session.commit()

    try:
        if source == "client":
            creator = db.session.get(User, uid)
            if creator and creator.email:
                send_ticket_created_client(ticket.title, ticket.id, ticket.priority, [creator.email])
        if ticket.assignee_id:
            assignee = db.session.get(User, ticket.assignee_id)
            if assignee and assignee.email:
                send_ticket_assigned(ticket.title, ticket.id, _customer_name(ticket.customer_id),
                                     ticket.priority, assignee.email)
    except Exception:
        current_app.logger.warning("Ticket create notification failed for ticket %s", ticket.id)

    try:
        from utils.events import publish_event
        publish_event("new_ticket", {
            "ticket_id": ticket.id,
            "title": ticket.title,
            "priority": ticket.priority,
            "source": source,
            "customer": _customer_name(ticket.customer_id),
        })
    except Exception:
        pass

    return jsonify(ticket.to_dict()), 201


@tickets_bp.route("/<ticket_id>", methods=["GET"])
@jwt_required()
def get_ticket(ticket_id):
    claims = _current_claims()
    role = claims.get("role")
    uid = get_jwt_identity()

    ticket = db.get_or_404(Ticket, ticket_id)

    # Client can only view their own customer's tickets
    if role == "client":
        user = db.session.get(User, uid)
        if not user or ticket.customer_id != user.customer_id:
            return jsonify({"error": "Not found"}), 404

    return jsonify(ticket.to_dict(include_comments=True)), 200


@tickets_bp.route("/<ticket_id>", methods=["PUT"])
@jwt_required()
@validate_body(TicketUpdateSchema)
def update_ticket(ticket_id):
    claims = _current_claims()
    role = claims.get("role")
    uid = get_jwt_identity()

    ticket = db.get_or_404(Ticket, ticket_id)

    # Clients cannot update tickets (read + create + comment only)
    if role == "client":
        return jsonify({"error": "Insufficient permissions"}), 403

    data = request.get_json(silent=True) or {}
    old_assignee_id = ticket.assignee_id
    old_status = ticket.status

    # Require a comment whenever the status is being changed
    new_status = data.get("status")
    if new_status and new_status != old_status:
        status_comment = (data.get("status_comment") or "").strip()
        if not status_comment:
            return jsonify({
                "error": f"A comment is required when changing status from '{old_status}' to '{new_status}'."
            }), 400

    tracked = ["title", "description", "assignee_id", "department_id", "priority", "status", "due_date", "tags"]
    changes = {f: {"from": getattr(ticket, f), "to": data[f]} for f in tracked if f in data and data[f] != getattr(ticket, f)}

    for field in tracked:
        if field in data:
            setattr(ticket, field, data[field])
    if data.get("status") in ("resolved", "closed") and not ticket.resolved_at:
        ticket.resolved_at = datetime.now(timezone.utc)
    ticket.updated_at = datetime.now(timezone.utc)
    _ticket_audit("UPDATE", uid, ticket_id, {"changes": changes})

    # Auto-post the status change comment so the thread stays conversational
    if new_status and new_status != old_status:
        status_comment_body = (
            f"[Status changed: {old_status.replace('_', ' ')} → {new_status.replace('_', ' ')}]\n\n"
            + status_comment
        )
        auto_comment = TicketComment(
            ticket_id=ticket_id,
            author_id=uid,
            body=status_comment_body,
            is_internal=False,
        )
        db.session.add(auto_comment)
        if not ticket.first_response_at:
            ticket.first_response_at = datetime.now(timezone.utc)

    db.session.commit()

    try:
        new_assignee_id = data.get("assignee_id")
        if new_assignee_id and new_assignee_id != old_assignee_id:
            assignee = db.session.get(User, new_assignee_id)
            if assignee and assignee.email:
                send_ticket_assigned(ticket.title, ticket.id, _customer_name(ticket.customer_id),
                                     ticket.priority, assignee.email)
        new_status = data.get("status")
        if new_status in ("resolved", "closed") and old_status not in ("resolved", "closed"):
            client_emails = _get_client_emails(ticket.customer_id)
            send_ticket_resolved_client(ticket.title, ticket.id, client_emails, ticket.requester_email)
    except Exception:
        current_app.logger.warning("Ticket update notification failed for ticket %s", ticket.id)

    return jsonify(ticket.to_dict()), 200


@tickets_bp.route("/<ticket_id>", methods=["DELETE"])
@jwt_required()
def delete_ticket(ticket_id):
    err = _require_role("admin", "technician")
    if err:
        return err
    uid = get_jwt_identity()
    ticket = db.get_or_404(Ticket, ticket_id)
    _ticket_audit("DELETE", uid, ticket_id, {"title": ticket.title})
    db.session.delete(ticket)
    db.session.commit()
    return jsonify({"message": "Ticket deleted"}), 200


@tickets_bp.route("/<ticket_id>/comments", methods=["POST"])
@jwt_required()
@validate_body(CommentCreateSchema)
def add_comment(ticket_id):
    claims = _current_claims()
    role = claims.get("role")
    uid = get_jwt_identity()

    ticket = db.get_or_404(Ticket, ticket_id)

    # Client can only comment on their own customer's tickets
    if role == "client":
        user = db.session.get(User, uid)
        if not user or ticket.customer_id != user.customer_id:
            return jsonify({"error": "Not found"}), 404

    data = request.get_json(silent=True) or {}
    if not data.get("body"):
        return jsonify({"error": "body required"}), 400

    # Clients cannot post internal notes
    is_internal = data.get("is_internal", False) if role != "client" else False

    comment = TicketComment(
        ticket_id=ticket_id,
        author_id=uid,
        body=data["body"],
        is_internal=is_internal,
    )
    db.session.add(comment)
    # Record first staff response time (non-client, non-internal)
    if role != "client" and not is_internal and not ticket.first_response_at:
        ticket.first_response_at = datetime.now(timezone.utc)
    _ticket_audit("COMMENT", uid, ticket_id, {"is_internal": is_internal, "preview": data["body"][:120]})
    db.session.commit()

    try:
        if not is_internal:
            if role == "client":
                if ticket.assignee_id:
                    assignee = db.session.get(User, ticket.assignee_id)
                    if assignee and assignee.email:
                        send_ticket_comment_to_assignee(ticket.title, ticket.id, data["body"], assignee.email)
            else:
                client_emails = _get_client_emails(ticket.customer_id)
                send_ticket_comment_to_client(
                    ticket.title, ticket.id, data["body"],
                    client_emails, ticket.requester_email,
                )
    except Exception:
        current_app.logger.warning("Comment notification failed for ticket %s", ticket.id)

    return jsonify(comment.to_dict()), 201


@tickets_bp.route("/<ticket_id>/comments/<comment_id>", methods=["DELETE"])
@jwt_required()
def delete_comment(ticket_id, comment_id):
    uid = get_jwt_identity()
    claims = get_jwt()
    role = claims.get("role")
    comment = TicketComment.query.filter_by(
        id=comment_id, ticket_id=ticket_id
    ).first_or_404()
    if role not in ("admin", "superadmin") and comment.author_id != uid:
        return jsonify({"error": "Cannot delete another user's comment"}), 403
    _ticket_audit("DELETE_COMMENT", uid, ticket_id, {"comment_id": comment_id})
    db.session.delete(comment)
    db.session.commit()
    return jsonify({"message": "Comment deleted"}), 200
