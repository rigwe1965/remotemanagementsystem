import os
import io
import smtplib
import logging
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import jwt_required, get_jwt
from extensions import db
from models.billing import Invoice
from models.customer import Customer
from models.device import Device
from utils.validation import validate_body
from schemas.billing import GenerateInvoiceSchema, InvoiceStatusSchema

logger = logging.getLogger(__name__)
billing_bp = Blueprint("billing", __name__)


def _require_role(*roles):
    claims = get_jwt()
    if claims.get("role") == "superadmin":
        return None
    if claims.get("role") not in roles:
        return jsonify({"error": "Insufficient permissions"}), 403
    return None


def _next_invoice_number():
    """Generate sequential INV-YYYY-NNNN number."""
    year = datetime.now(timezone.utc).year
    count = Invoice.query.filter(
        Invoice.invoice_number.like(f"INV-{year}-%")
    ).count()
    return f"INV-{year}-{count + 1:04d}"


@billing_bp.route("/tier-features", methods=["GET"])
@jwt_required()
def get_tier_features():
    """
    Return the feature set for the caller's tier.
    Used by the React frontend to gate premium UI elements.
    """
    from utils.tier_gates import tier_features, _get_customer_tier_from_jwt
    current_tier = _get_customer_tier_from_jwt()
    return jsonify({
        "tier": current_tier,
        "features": tier_features(current_tier),
    }), 200


@billing_bp.route("/invoices", methods=["GET"])
@jwt_required()
def list_invoices():
    err = _require_role("admin", "technician", "viewer")
    if err:
        return err
    customer_id = request.args.get("customer_id")
    query = Invoice.query
    if customer_id:
        query = query.filter_by(customer_id=customer_id)
    invoices = query.order_by(Invoice.created_at.desc()).limit(100).all()
    return jsonify([i.to_dict() for i in invoices]), 200


@billing_bp.route("/invoices/generate", methods=["POST"])
@jwt_required()
@validate_body(GenerateInvoiceSchema)
def generate_invoice():
    err = _require_role("admin")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    customer_id = data.get("customer_id")
    if not customer_id:
        return jsonify({"error": "customer_id required"}), 400

    device_count = Device.query.filter_by(customer_id=customer_id).count()
    per_device_rate = float(data.get("per_device_rate", 15.00))
    subtotal = device_count * per_device_rate
    tax_rate = float(data.get("tax_rate", 0.0))
    tax = subtotal * tax_rate
    total = subtotal + tax

    period_start = (
        datetime.fromisoformat(data["period_start"])
        if data.get("period_start") else datetime.now(timezone.utc)
    )
    period_end = (
        datetime.fromisoformat(data["period_end"])
        if data.get("period_end") else datetime.now(timezone.utc)
    )

    due_date_raw = data.get("due_date")
    if due_date_raw:
        due_date = datetime.fromisoformat(due_date_raw)
    else:
        due_date = period_end + timedelta(days=30)

    invoice = Invoice(
        invoice_number=_next_invoice_number(),
        customer_id=customer_id,
        period_start=period_start,
        period_end=period_end,
        due_date=due_date,
        device_count=device_count,
        per_device_rate=per_device_rate,
        subtotal=subtotal,
        tax_rate=tax_rate,
        tax=tax,
        total=total,
        notes=data.get("notes") or None,
        line_items=[
            {
                "description": f"Managed Devices — Service Period",
                "quantity": device_count,
                "rate": per_device_rate,
                "amount": subtotal,
            },
        ],
    )
    db.session.add(invoice)
    db.session.commit()
    return jsonify(invoice.to_dict()), 201


@billing_bp.route("/invoices/<invoice_id>", methods=["GET"])
@jwt_required()
def get_invoice(invoice_id):
    invoice = db.get_or_404(Invoice, invoice_id)
    return jsonify(invoice.to_dict()), 200


@billing_bp.route("/invoices/<invoice_id>/pdf", methods=["GET"])
@jwt_required()
def get_invoice_pdf(invoice_id):
    invoice = db.get_or_404(Invoice, invoice_id)
    customer = db.get_or_404(Customer, invoice.customer_id)

    from models.org_settings import OrgSettings
    org = db.session.get(OrgSettings, 1) or OrgSettings(id=1)

    from utils.invoice_pdf import generate_invoice_pdf
    pdf_bytes = generate_invoice_pdf(invoice, customer, org)

    inv_num = invoice.invoice_number or invoice.id[:8]
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="invoice-{inv_num}.pdf"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )


@billing_bp.route("/invoices/<invoice_id>/send-email", methods=["POST"])
@jwt_required()
def send_invoice_email(invoice_id):
    err = _require_role("admin")
    if err:
        return err

    invoice = db.get_or_404(Invoice, invoice_id)
    customer = db.get_or_404(Customer, invoice.customer_id)

    if not customer.email:
        return jsonify({"error": "Customer has no email address on file"}), 400

    smtp_host = os.getenv("SMTP_HOST", "")
    if not smtp_host:
        return jsonify({"error": "SMTP not configured — set SMTP_HOST in .env to enable email delivery"}), 503

    from models.org_settings import OrgSettings
    org = db.session.get(OrgSettings, 1) or OrgSettings(id=1)

    from utils.invoice_pdf import generate_invoice_pdf
    pdf_bytes = generate_invoice_pdf(invoice, customer, org)

    inv_num = invoice.invoice_number or invoice.id[:8]
    company_name = org.company_name or "RMM System"
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user or "billing@localhost")

    subject = f"Invoice {inv_num} from {company_name}"
    body_html = f"""
<p>Dear {customer.name},</p>
<p>Please find attached your invoice <strong>{inv_num}</strong>.</p>
<table style="border-collapse:collapse;margin:16px 0">
  <tr><td style="padding:4px 12px 4px 0;color:#6B7B6B">Invoice Number:</td><td><strong>{inv_num}</strong></td></tr>
  <tr><td style="padding:4px 12px 4px 0;color:#6B7B6B">Amount Due:</td><td><strong>${float(invoice.total):,.2f}</strong></td></tr>
  <tr><td style="padding:4px 12px 4px 0;color:#6B7B6B">Due Date:</td><td>{invoice.due_date.strftime("%d %B %Y") if invoice.due_date else "—"}</td></tr>
</table>
<p>Please do not hesitate to contact us if you have any questions.</p>
<p style="color:#6B7B6B;font-size:13px">{org.footer_notes or "Thank you for your business!"}</p>
<p style="color:#6B7B6B;font-size:12px">— {company_name}</p>
"""

    try:
        msg = MIMEMultipart()
        msg["From"] = smtp_from
        msg["To"] = customer.email
        msg["Subject"] = subject
        msg.attach(MIMEText(body_html, "html"))

        part = MIMEBase("application", "pdf")
        part.set_payload(pdf_bytes)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="invoice-{inv_num}.pdf"')
        msg.attach(part)

        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
            server.ehlo()
            if smtp_port != 25:
                server.starttls()
            if smtp_user:
                server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, [customer.email], msg.as_string())

        logger.info("Invoice %s emailed to %s", inv_num, customer.email)
        return jsonify({"message": f"Invoice {inv_num} sent to {customer.email}"}), 200

    except Exception as exc:
        logger.warning("Failed to email invoice %s: %s", inv_num, exc)
        return jsonify({"error": f"Email delivery failed: {exc}"}), 500


@billing_bp.route("/invoices/<invoice_id>/send", methods=["POST"])
@jwt_required()
def send_invoice(invoice_id):
    err = _require_role("admin")
    if err:
        return err
    invoice = db.get_or_404(Invoice, invoice_id)
    invoice.status = "sent"
    invoice.sent_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"message": "Invoice marked as sent", "invoice": invoice.to_dict()}), 200


@billing_bp.route("/invoices/<invoice_id>/status", methods=["PATCH"])
@jwt_required()
@validate_body(InvoiceStatusSchema)
def update_invoice_status(invoice_id):
    """Set invoice status to: sent | paid | overdue | draft."""
    err = _require_role("admin")
    if err:
        return err
    invoice = db.get_or_404(Invoice, invoice_id)
    data = request.get_json(silent=True) or {}
    new_status = data.get("status", "").lower()
    allowed = {"draft", "sent", "paid", "overdue"}
    if new_status not in allowed:
        return jsonify({"error": f"status must be one of {sorted(allowed)}"}), 400
    invoice.status = new_status
    if new_status == "sent" and not invoice.sent_at:
        invoice.sent_at = datetime.now(timezone.utc)
    if new_status == "paid":
        invoice.paid_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"message": f"Invoice marked as {new_status}", "invoice": invoice.to_dict()}), 200


@billing_bp.route("/invoices/<invoice_id>", methods=["DELETE"])
@jwt_required()
def delete_invoice(invoice_id):
    err = _require_role("admin")
    if err:
        return err
    invoice = db.get_or_404(Invoice, invoice_id)
    db.session.delete(invoice)
    db.session.commit()
    return jsonify({"message": "Invoice deleted"}), 200


@billing_bp.route("/invoices/<invoice_id>/payment_link", methods=["POST"])
@jwt_required()
def get_payment_link(invoice_id):
    """Generate a Stripe Checkout URL for this invoice."""
    err = _require_role("admin", "technician")
    if err:
        return err

    from utils.stripe_client import create_checkout_session, stripe_configured
    if not stripe_configured():
        return jsonify({"error": "Stripe not configured — add STRIPE_SECRET_KEY to .env"}), 503

    invoice = db.get_or_404(Invoice, invoice_id)
    if invoice.status == "paid":
        return jsonify({"error": "Invoice already paid"}), 400

    customer = db.session.get(Customer, invoice.customer_id)
    customer_email = customer.email if customer else None

    url, err_msg = create_checkout_session(invoice, customer_email)
    if err_msg:
        return jsonify({"error": err_msg}), 500

    # Store session ID for later webhook matching
    invoice.stripe_checkout_session_id = url.split("/")[-1] if url else None
    db.session.commit()

    return jsonify({"checkout_url": url, "invoice_id": invoice_id}), 200


@billing_bp.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    """Stripe webhook — no JWT, verified by signature."""
    from utils.stripe_client import verify_webhook

    payload    = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")

    event, err_msg = verify_webhook(payload, sig_header)
    if err_msg:
        logger.warning("Stripe webhook verify failed: %s", err_msg)
        return jsonify({"error": err_msg}), 400

    event_type = event.get("type", "")
    logger.info("Stripe webhook received: %s", event_type)

    if event_type == "checkout.session.completed":
        session    = event["data"]["object"]
        invoice_id = (session.get("metadata") or {}).get("invoice_id")
        if invoice_id:
            invoice = db.session.get(Invoice, invoice_id)
            if invoice and invoice.status != "paid":
                invoice.status                   = "paid"
                invoice.paid_at                  = datetime.now(timezone.utc)
                invoice.stripe_checkout_session_id = session.get("id")
                invoice.stripe_payment_intent_id   = session.get("payment_intent")
                db.session.commit()
                logger.info("Invoice %s marked paid via Stripe", invoice_id)

    return jsonify({"received": True}), 200
