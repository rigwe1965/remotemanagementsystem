import uuid
from datetime import datetime, timezone
from extensions import db


class TriageCategory(db.Model):
    """Curated whitelist of AI ticket-triage categories. A category only becomes
    eligible for auto-resolve when an admin explicitly sets auto_resolve_enabled
    and turns off shadow_mode — see services/ticket_triage_service.py for the
    server-side gate that reads these fields (never the model's own opinion)."""
    __tablename__ = "triage_categories"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    label = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)  # fed into the AI prompt as the category's definition
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    auto_resolve_enabled = db.Column(db.Boolean, default=False, nullable=False)  # the curated-whitelist flag
    shadow_mode = db.Column(db.Boolean, default=True, nullable=False)  # human-approval-required flag
    confidence_threshold = db.Column(db.Float, default=0.85, nullable=False)
    auto_close_days = db.Column(db.Integer, nullable=True)  # NULL = use AI_TRIAGE_AUTO_CLOSE_DAYS global default
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "label": self.label,
            "description": self.description,
            "is_active": self.is_active,
            "auto_resolve_enabled": self.auto_resolve_enabled,
            "shadow_mode": self.shadow_mode,
            "confidence_threshold": self.confidence_threshold,
            "auto_close_days": self.auto_close_days,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
