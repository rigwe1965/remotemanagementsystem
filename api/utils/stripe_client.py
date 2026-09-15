"""Stripe integration — silently no-ops if STRIPE_SECRET_KEY not set."""
import os
import logging

logger = logging.getLogger(__name__)


def _stripe():
    """Import and configure stripe lazily. Returns None if not configured."""
    key = os.getenv("STRIPE_SECRET_KEY", "")
    if not key:
        return None
    try:
        import stripe as _stripe_lib
        _stripe_lib.api_key = key
        return _stripe_lib
    except ImportError:
        logger.warning("stripe package not installed — run: pip install stripe")
        return None


def create_checkout_session(invoice, customer_email: str = None) -> tuple:
    """
    Create a Stripe Checkout Session for an invoice.
    Returns (checkout_url, error_string).
    """
    stripe = _stripe()
    if not stripe:
        return None, "Stripe not configured — set STRIPE_SECRET_KEY in .env"

    dashboard_url = os.getenv("API_BASE_URL", "http://localhost:5000")
    success_url = os.getenv("STRIPE_SUCCESS_URL", f"{dashboard_url}/stripe/success?invoice_id={invoice.id}")
    cancel_url  = os.getenv("STRIPE_CANCEL_URL",  f"{dashboard_url}/stripe/cancel?invoice_id={invoice.id}")

    try:
        from extensions import db
        from models.org_settings import OrgSettings
        org = db.session.get(OrgSettings, 1)
        currency = (org.currency if org and org.currency else "usd").lower()
    except Exception:
        currency = "usd"

    inv_num = invoice.invoice_number or invoice.id[:8].upper()
    period_start = invoice.period_start.strftime("%Y-%m-%d") if invoice.period_start else "—"
    period_end   = invoice.period_end.strftime("%Y-%m-%d")   if invoice.period_end   else "—"

    amount_cents = int(float(invoice.total) * 100)
    if amount_cents <= 0:
        return None, "Invoice total must be greater than zero"

    try:
        params = {
            "payment_method_types": ["card"],
            "line_items": [{
                "price_data": {
                    "currency": currency,
                    "unit_amount": amount_cents,
                    "product_data": {
                        "name": f"Invoice {inv_num}",
                        "description": f"Service period {period_start} → {period_end}",
                    },
                },
                "quantity": 1,
            }],
            "mode": "payment",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata": {"invoice_id": invoice.id, "invoice_number": inv_num},
        }
        if customer_email:
            params["customer_email"] = customer_email

        session = stripe.checkout.Session.create(**params)
        return session.url, None

    except Exception as exc:
        logger.error("Stripe checkout session creation failed: %s", exc)
        return None, str(exc)


def verify_webhook(payload: bytes, sig_header: str) -> tuple:
    """
    Verify Stripe webhook signature and return (event, error).
    """
    stripe = _stripe()
    if not stripe:
        return None, "Stripe not configured"

    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        return None, "STRIPE_WEBHOOK_SECRET not set"

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
        return event, None
    except Exception as exc:
        return None, str(exc)


def stripe_configured() -> bool:
    return bool(os.getenv("STRIPE_SECRET_KEY", ""))
