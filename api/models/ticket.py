import uuid
from datetime import datetime, timezone
from extensions import db


class Ticket(db.Model):
    __tablename__ = "tickets"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text, nullable=True)
    customer_id = db.Column(db.String(36), db.ForeignKey("customers.id"), nullable=False, index=True)
    device_id = db.Column(db.String(36), db.ForeignKey("devices.id"), nullable=True)
    assignee_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True)
    priority = db.Column(db.String(20), default="medium")  # low/medium/high/critical
    status = db.Column(db.String(30), default="open")  # open/in_progress/resolved/closed
    source = db.Column(db.String(30), default="manual")  # manual/alert/client
    department_id = db.Column(db.String(36), db.ForeignKey("departments.id"), nullable=True)
    alert_id = db.Column(db.String(36), db.ForeignKey("alerts.id"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))
    resolved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    due_date = db.Column(db.DateTime(timezone=True), nullable=True)
    first_response_at = db.Column(db.DateTime(timezone=True), nullable=True)
    sla_breached = db.Column(db.Boolean, default=False, nullable=False)
    tags = db.Column(db.JSON, default=list)
    email_thread_id = db.Column(db.String(500), nullable=True, index=True)
    requester_email = db.Column(db.String(255), nullable=True)
    requester_name = db.Column(db.String(255), nullable=True)

    # ── AI triage (see services/ticket_triage_service.py) ──────────────────────
    category = db.Column(db.String(50), nullable=True, index=True)
    ai_suggested_category = db.Column(db.String(50), nullable=True)
    ai_confidence = db.Column(db.Float, nullable=True)
    ai_suggested_reply = db.Column(db.Text, nullable=True)
    ai_reasoning = db.Column(db.Text, nullable=True)  # internal-only — never emailed to the customer
    triage_status = db.Column(db.String(20), nullable=True, index=True)
    # pending/escalated/staged/auto_resolved/reopened/skipped/error
    auto_resolved = db.Column(db.Boolean, default=False, nullable=False)
    triage_model = db.Column(db.String(60), nullable=True)
    triaged_at = db.Column(db.DateTime(timezone=True), nullable=True)

    comments = db.relationship("TicketComment", backref="ticket", lazy="dynamic",
                               cascade="all, delete-orphan")

    def to_dict(self, include_comments=False):
        d = {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "customer_id": self.customer_id,
            "device_id": self.device_id,
            "assignee_id": self.assignee_id,
            "priority": self.priority,
            "status": self.status,
            "source": self.source,
            "alert_id": self.alert_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "first_response_at": self.first_response_at.isoformat() if self.first_response_at else None,
            "sla_breached": self.sla_breached,
            "tags": self.tags,
            "department_id": self.department_id,
            "email_thread_id": self.email_thread_id,
            "requester_email": self.requester_email,
            "requester_name": self.requester_name,
            "category": self.category,
            "ai_suggested_category": self.ai_suggested_category,
            "ai_confidence": self.ai_confidence,
            "ai_suggested_reply": self.ai_suggested_reply,
            "ai_reasoning": self.ai_reasoning,
            "triage_status": self.triage_status,
            "auto_resolved": self.auto_resolved,
            "triage_model": self.triage_model,
            "triaged_at": self.triaged_at.isoformat() if self.triaged_at else None,
        }
        if include_comments:
            d["comments"] = [c.to_dict() for c in self.comments.order_by(TicketComment.created_at)]
        return d


class TicketComment(db.Model):
    __tablename__ = "ticket_comments"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    ticket_id = db.Column(db.String(36), db.ForeignKey("tickets.id"), nullable=False, index=True)
    author_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True)
    author_email = db.Column(db.String(255), nullable=True)
    body = db.Column(db.Text, nullable=False)
    is_internal = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    author = db.relationship("User", foreign_keys=[author_id], lazy="joined")

    def to_dict(self):
        if self.author:
            author_name = self.author.full_name or self.author.email
        elif self.author_email:
            author_name = self.author_email
        else:
            author_name = "Unknown"
        return {
            "id": self.id,
            "ticket_id": self.ticket_id,
            "author_id": self.author_id,
            "author_email": self.author_email,
            "author_name": author_name,
            "body": self.body,
            "is_internal": self.is_internal,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
