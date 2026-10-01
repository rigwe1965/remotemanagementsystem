from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from extensions import db, limiter
from models.ticket import Ticket, TicketComment
from models.user import User
from models.audit import AuditLog
from utils.validation import validate_body
from utils.auth_decorators import require_role as _require_role
from utils.scope import require_customer_scope
from utils.pagination import paginated_response
from schemas.tickets import TicketCreateSchema, TicketUpdateSchema, CommentCreateSchema

tickets_bp = Blueprint("tickets", __name__)


def _current_claims():
    return get_jwt()


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
            return jsonify({"items": [], "total": 0, "page": page, "pages": 0}), 200
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

    return paginated_response(query, lambda t: t.to_dict(), order_by=Ticket.created_at.desc())


@tickets_bp.route("/", methods=["POST"])
@jwt_required()
@limiter.limit("20 per minute")
@validate_body(TicketCreateSchema)
def create_ticket():
    from services.ticket_service import create_ticket_service
    claims = _current_claims()
    role = claims.get("role")
    uid = get_jwt_identity()
    data = request.get_json(silent=True) or {}

    actor_customer_id = None
    if role == "client":
        user = db.session.get(User, uid)
        actor_customer_id = user.customer_id if user else None

    result, err = create_ticket_service(
        uid, role, actor_customer_id,
        title=data.get("title"), description=data.get("description"),
        customer_id=data.get("customer_id"), device_id=data.get("device_id"),
        assignee_id=data.get("assignee_id"), priority=data.get("priority", "medium"),
        status=data.get("status", "open"), alert_id=data.get("alert_id"),
        department_id=data.get("department_id"), tags=data.get("tags", []),
        due_date=data.get("due_date"), source=data.get("source", "manual"),
    )
    if err:
        return jsonify({"error": err[0]}), err[1]
    return jsonify(result), 201


@tickets_bp.route("/<ticket_id>", methods=["GET"])
@jwt_required()
def get_ticket(ticket_id):
    ticket = db.get_or_404(Ticket, ticket_id)

    err = require_customer_scope(ticket.customer_id)
    if err:
        return err

    return jsonify(ticket.to_dict(include_comments=True)), 200


@tickets_bp.route("/<ticket_id>", methods=["PUT"])
@jwt_required()
@validate_body(TicketUpdateSchema)
def update_ticket(ticket_id):
    from services.ticket_service import update_ticket_service
    claims = _current_claims()
    role = claims.get("role")
    uid = get_jwt_identity()

    ticket = db.get_or_404(Ticket, ticket_id)
    data = request.get_json(silent=True) or {}

    result, err = update_ticket_service(
        uid, role, ticket,
        status=data.get("status"), status_comment=data.get("status_comment"),
        assignee_id=data.get("assignee_id"), priority=data.get("priority"),
        title=data.get("title"), description=data.get("description"),
        department_id=data.get("department_id"), due_date=data.get("due_date"),
        tags=data.get("tags"),
    )
    if err:
        return jsonify({"error": err[0]}), err[1]
    return jsonify(result), 200


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
    from services.ticket_service import add_comment_service
    claims = _current_claims()
    role = claims.get("role")
    uid = get_jwt_identity()

    ticket = db.get_or_404(Ticket, ticket_id)

    err = require_customer_scope(ticket.customer_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    result, err2 = add_comment_service(
        uid, role, ticket,
        body=data.get("body", ""), is_internal=data.get("is_internal", False),
    )
    if err2:
        return jsonify({"error": err2[0]}), err2[1]
    return jsonify(result), 201


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
