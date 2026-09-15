import base64
import io
from extensions import db


class OrgSettings(db.Model):
    __tablename__ = "org_settings"

    id = db.Column(db.Integer, primary_key=True)  # always 1 — singleton
    company_name = db.Column(db.String(255), default="")
    company_address = db.Column(db.Text, default="")
    company_email = db.Column(db.String(255), default="")
    company_phone = db.Column(db.String(50), default="")
    logo_data = db.Column(db.Text, nullable=True)   # base64 data URI
    payment_terms = db.Column(db.String(100), default="Net 30")
    bank_details = db.Column(db.Text, default="")
    footer_notes = db.Column(db.Text, default="Thank you for your business!")
    # White-label branding
    app_name      = db.Column(db.String(100), default="RMM System")
    tagline       = db.Column(db.String(200), default="Remote Monitoring & Management")
    primary_color = db.Column(db.String(7),   default="#407E3C")
    # Regional settings
    currency      = db.Column(db.String(3),   default="USD")
    timezone      = db.Column(db.String(50),  default="UTC")

    def to_dict(self):
        return {
            "id": self.id,
            "company_name": self.company_name or "",
            "company_address": self.company_address or "",
            "company_email": self.company_email or "",
            "company_phone": self.company_phone or "",
            "logo_data": self.logo_data,
            "payment_terms": self.payment_terms or "Net 30",
            "bank_details": self.bank_details or "",
            "footer_notes":    self.footer_notes or "Thank you for your business!",
            "app_name":        self.app_name or "RMM System",
            "tagline":         self.tagline or "Remote Monitoring & Management",
            "primary_color":   self.primary_color or "#407E3C",
            "currency":        self.currency or "USD",
            "timezone":        self.timezone or "UTC",
        }

    def logo_bytes(self):
        """Return raw logo image bytes, or None if no logo set."""
        if not self.logo_data:
            return None
        try:
            _, b64 = self.logo_data.split(",", 1)
            return base64.b64decode(b64)
        except Exception:
            return None


def ensure_org_settings():
    """Create the singleton org settings row if it doesn't exist."""
    from extensions import db
    if not db.session.get(OrgSettings, 1):
        settings = OrgSettings(id=1)
        db.session.add(settings)
        db.session.commit()
