"""Ticket creation/update/comment logic shared by the human-facing routes, the AI
assistant tool executor, and (update/comment only) the AI triage pipeline.

Extracted from routes/tickets.py so every caller runs the exact same
authorization/SLA/audit/notification logic — no duplicated permission checks.
"""
import os
from datetime import datetime, timezone, timedelta

from flask import request, current_app
from extensions import db
from models.ticket import Ticket, TicketComment
from models.user import User
from models.customer import Customer
from models.audit import AuditLog


def _sla_resolution_hours(priority: str, customer_id: str) -> int:
    import time
    from models.sla_policy import SLAPolicy

    _SLA_HOURS = {"critical": 4, "high": 8, "medium": 24, "low": 72}
    if not hasattr(_sla_resolution_hours, "_cache"):
        _sla_resolution_hours._cache = {}
    cache = _sla_resolution_hours._cache
    ttl = 120

    key = (customer_id, priority)
    entry = cache.get(key)
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

    cache[key] = (hours, time.monotonic() + ttl)
    return hours


def _customer_name(customer_id: str) -> str:
    c = db.session.get(Customer, customer_id)
    return c.name if c else "Unknown"


def create_ticket_service(
    actor_user_id: str,
    actor_role: str,
    actor_customer_id: str,
    *,
    title: str,
    description: str = None,
    customer_id: str = None,
    device_id: str = None,
    assignee_id: str = None,
    priority: str = "medium",
    status: str = "open",
    alert_id: str = None,
    department_id: str = None,
    tags: list = None,
    due_date=None,
    source: str = "manual",
    requester_email: str = None,
    requester_name: str = None,
    email_thread_id: str = None,
):
    """Returns (ticket_dict, error) where error is None or (message, status_code).

    actor_role="system" (actor_user_id=None) is used by the email poller
    (tasks/email_tasks.py) for inbound-email-originated tickets."""
    if actor_role not in ("admin", "technician", "client", "superadmin", "system"):
        return None, ("Insufficient permissions", 403)

    if actor_role == "client":
        if not actor_customer_id:
            return None, ("Client account not linked to a customer", 400)
        resolved_customer_id = actor_customer_id
        source = "client"
        dept_id = current_app.config.get("HELPDESK_DEPT_ID")
    else:
        resolved_customer_id = customer_id
        if not resolved_customer_id:
            return None, ("customer_id required", 400)
        dept_id = department_id

    title = (title or "").strip()
    if not title:
        return None, ("title required", 400)

    due_date = due_date or (
        datetime.now(timezone.utc) + timedelta(hours=_sla_resolution_hours(priority, resolved_customer_id))
    )
    ticket = Ticket(
        title=title,
        description=description,
        customer_id=resolved_customer_id,
        device_id=device_id,
        assignee_id=assignee_id,
        priority=priority,
        status=status,
        source=source,
        alert_id=alert_id,
        department_id=dept_id,
        due_date=due_date,
        tags=tags or [],
        requester_email=requester_email,
        requester_name=requester_name,
        email_thread_id=email_thread_id,
        triage_status="pending",
    )
    db.session.add(ticket)
    db.session.flush()  # populate ticket.id (client-side UUID default) before referencing it below
    db.session.add(AuditLog(
        user_id=actor_user_id,
        action="CREATE",
        resource_type="ticket",
        resource_id=ticket.id,
        ip_address=request.remote_addr if request else None,
        user_agent=(request.headers.get("User-Agent", "")[:500] if request else None),
        payload={"title": ticket.title, "priority": ticket.priority, "source": source},
    ))
    db.session.commit()

    try:
        from utils.notifications import send_ticket_created_client, send_ticket_assigned
        if source == "client":
            creator = db.session.get(User, actor_user_id)
            if creator and creator.email:
                send_ticket_created_client(ticket.title, ticket.id, ticket.priority, [creator.email])
        if ticket.assignee_id:
            assignee = db.session.get(User, ticket.assignee_id)
            if assignee and assignee.email:
                send_ticket_assigned(ticket.title, ticket.id, _customer_name(ticket.customer_id),
                                     ticket.priority, assignee.email)
    except Exception:
        current_app.logger.warning("Ticket create notification failed for ticket %s", ticket.id, exc_info=True)

    # publish_event() already catches and logs internally — it never raises — so no
    # try/except needed here (see api/utils/events.py::publish_event).
    from utils.events import publish_event
    publish_event("new_ticket", {
        "ticket_id": ticket.id,
        "title": ticket.title,
        "priority": ticket.priority,
        "source": source,
        "customer": _customer_name(ticket.customer_id),
    })

    # AI triage runs async (Celery) so an Anthropic outage / rate limit never
    # fails ticket creation — this is the single scheduling point every caller
    # (this route, the AI assistant's create_ticket tool, and the email poller)
    # goes through, so every new ticket gets triaged regardless of source.
    if os.getenv("AI_TRIAGE_ENABLED", "true").lower() != "false":
        try:
            from tasks.triage_tasks import triage_ticket
            triage_ticket.delay(ticket.id)
        except Exception:
            current_app.logger.warning("Failed to schedule triage for ticket %s", ticket.id, exc_info=True)

    return ticket.to_dict(), None


# ── Update / comment — extracted from routes/tickets.py so the AI triage
# pipeline (apply/approve/reopen) and the human-facing route share one
# implementation instead of a third copy of the same status-change rules. ──

def update_ticket_service(
    actor_user_id: str,
    actor_role: str,
    ticket: Ticket,
    *,
    status: str = None,
    status_comment: str = None,
    assignee_id: str = None,
    priority: str = None,
    title: str = None,
    description: str = None,
    department_id: str = None,
    due_date=None,
    tags: list = None,
    skip_status_comment_requirement: bool = False,
):
    """Returns (ticket_dict, error). `skip_status_comment_requirement=True` lets
    system callers (AI triage, reopen-on-reply) transition status without a
    human-authored comment — they synthesize their own instead."""
    if actor_role == "client":
        return None, ("Insufficient permissions", 403)

    old_assignee_id = ticket.assignee_id
    old_status = ticket.status

    if status and status != old_status and not skip_status_comment_requirement:
        if not (status_comment or "").strip():
            return None, (
                f"A comment is required when changing status from '{old_status}' to '{status}'.", 400
            )

    data = {}
    if title is not None:
        data["title"] = title
    if description is not None:
        data["description"] = description
    if assignee_id is not None:
        data["assignee_id"] = assignee_id
    if department_id is not None:
        data["department_id"] = department_id
    if priority is not None:
        data["priority"] = priority
    if status is not None:
        data["status"] = status
    if due_date is not None:
        data["due_date"] = due_date
    if tags is not None:
        data["tags"] = tags

    tracked = ["title", "description", "assignee_id", "department_id", "priority", "status", "due_date", "tags"]
    changes = {f: {"from": getattr(ticket, f), "to": data[f]} for f in tracked if f in data and data[f] != getattr(ticket, f)}

    for field in tracked:
        if field in data:
            setattr(ticket, field, data[field])
    if data.get("status") in ("resolved", "closed") and not ticket.resolved_at:
        ticket.resolved_at = datetime.now(timezone.utc)
    ticket.updated_at = datetime.now(timezone.utc)

    db.session.add(AuditLog(
        user_id=actor_user_id,
        action="UPDATE",
        resource_type="ticket",
        resource_id=ticket.id,
        ip_address=request.remote_addr if request else None,
        user_agent=(request.headers.get("User-Agent", "")[:500] if request else None),
        payload={"changes": changes},
    ))

    if status and status != old_status:
        comment_text = (status_comment or "").strip() or "Status changed automatically."
        status_comment_body = (
            f"[Status changed: {old_status.replace('_', ' ')} → {status.replace('_', ' ')}]\n\n"
            + comment_text
        )
        db.session.add(TicketComment(
            ticket_id=ticket.id,
            author_id=actor_user_id,
            author_email=None if actor_user_id else "system",
            body=status_comment_body,
            is_internal=False,
        ))
        if not ticket.first_response_at:
            ticket.first_response_at = datetime.now(timezone.utc)

    db.session.commit()

    try:
        from utils.notifications import send_ticket_assigned, send_ticket_resolved_client
        new_assignee_id = data.get("assignee_id")
        if new_assignee_id and new_assignee_id != old_assignee_id:
            assignee = db.session.get(User, new_assignee_id)
            if assignee and assignee.email:
                send_ticket_assigned(ticket.title, ticket.id, _customer_name(ticket.customer_id),
                                     ticket.priority, assignee.email)
        if data.get("status") in ("resolved", "closed") and old_status not in ("resolved", "closed"):
            client_emails = _get_client_emails(ticket.customer_id)
            send_ticket_resolved_client(ticket.title, ticket.id, client_emails, ticket.requester_email)
    except Exception:
        current_app.logger.warning("Ticket update notification failed for ticket %s", ticket.id, exc_info=True)

    return ticket.to_dict(), None


def add_comment_service(
    actor_user_id: str,
    actor_role: str,
    ticket: Ticket,
    *,
    body: str,
    is_internal: bool = False,
    author_email: str = None,
):
    """Returns (comment_dict, error). `author_email` (no `actor_user_id`) is used
    for system/email-authored comments — matches what the email poller already
    did inline before this was extracted."""
    if not (body or "").strip():
        return None, ("body required", 400)

    is_internal = is_internal if actor_role != "client" else False

    comment = TicketComment(
        ticket_id=ticket.id,
        author_id=actor_user_id,
        author_email=author_email,
        body=body,
        is_internal=is_internal,
    )
    db.session.add(comment)
    if actor_role not in ("client", "system") and not is_internal and not ticket.first_response_at:
        ticket.first_response_at = datetime.now(timezone.utc)

    db.session.add(AuditLog(
        user_id=actor_user_id,
        action="COMMENT",
        resource_type="ticket",
        resource_id=ticket.id,
        ip_address=request.remote_addr if request else None,
        user_agent=(request.headers.get("User-Agent", "")[:500] if request else None),
        payload={"is_internal": is_internal, "preview": body[:120]},
    ))
    db.session.commit()

    try:
        from utils.notifications import send_ticket_comment_to_client, send_ticket_comment_to_assignee
        if not is_internal:
            if actor_role == "client":
                if ticket.assignee_id:
                    assignee = db.session.get(User, ticket.assignee_id)
                    if assignee and assignee.email:
                        send_ticket_comment_to_assignee(ticket.title, ticket.id, body, assignee.email)
            elif actor_role != "system":
                client_emails = _get_client_emails(ticket.customer_id)
                send_ticket_comment_to_client(ticket.title, ticket.id, body, client_emails, ticket.requester_email)
    except Exception:
        current_app.logger.warning("Comment notification failed for ticket %s", ticket.id, exc_info=True)

    return comment.to_dict(), None


def _get_client_emails(customer_id: str) -> list:
    clients = User.query.filter_by(role="client", customer_id=customer_id, is_active=True).all()
    return [u.email for u in clients if u.email]
