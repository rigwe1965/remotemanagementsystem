"""
Pricing tier enforcement.

Tiers (ascending): standard < premium < enterprise

Usage in a route:
    from utils.tier_gates import require_tier, customer_tier_from_jwt

    @billing_bp.route("/some-premium-feature")
    @jwt_required()
    def premium_endpoint():
        err = require_tier("premium")
        if err:
            return err
        ...
"""
import logging
from functools import wraps

from flask import jsonify, request
from flask_jwt_extended import get_jwt

logger = logging.getLogger(__name__)

TIER_ORDER = {"standard": 0, "premium": 1, "enterprise": 2}

TIER_FEATURES = {
    "standard": {
        "max_devices": 25,
        "max_users": 5,
        "ai_anomaly_detection": False,
        "advanced_reports": False,
        "custom_scripts": False,
        "api_access": False,
        "sla_policies": False,
        "white_label": False,
        "webhook_integrations": False,
        "iot_sensors": False,
    },
    "premium": {
        "max_devices": 250,
        "max_users": 25,
        "ai_anomaly_detection": True,
        "advanced_reports": True,
        "custom_scripts": True,
        "api_access": True,
        "sla_policies": True,
        "white_label": False,
        "webhook_integrations": True,
        "iot_sensors": True,
    },
    "enterprise": {
        "max_devices": None,  # unlimited
        "max_users": None,
        "ai_anomaly_detection": True,
        "advanced_reports": True,
        "custom_scripts": True,
        "api_access": True,
        "sla_policies": True,
        "white_label": True,
        "webhook_integrations": True,
        "iot_sensors": True,
    },
}


def _get_customer_tier_from_jwt() -> str:
    """Extract customer tier from JWT claims. Falls back to 'standard'."""
    claims = get_jwt()
    # superadmin / internal staff have no customer tier limit
    if claims.get("role") in ("superadmin", "admin", "technician", "viewer"):
        return "enterprise"
    return claims.get("customer_tier", "standard")


def require_tier(minimum_tier: str):
    """
    Check that the caller's customer tier meets minimum_tier.
    Returns (jsonify response, 402) on failure, None on success.
    """
    if minimum_tier not in TIER_ORDER:
        raise ValueError(f"Unknown tier: {minimum_tier}")

    current = _get_customer_tier_from_jwt()
    current_rank = TIER_ORDER.get(current, 0)
    required_rank = TIER_ORDER[minimum_tier]

    if current_rank < required_rank:
        return jsonify({
            "error": "tier_upgrade_required",
            "message": f"This feature requires the '{minimum_tier}' plan or above.",
            "current_tier": current,
            "required_tier": minimum_tier,
        }), 402

    return None


def check_device_limit(customer_id: str) -> tuple:
    """
    Check if customer has reached their device limit.
    Returns (at_limit: bool, limit: int|None, current: int).
    """
    try:
        from extensions import db
        from models.customer import Customer
        from models.device import Device
        customer = db.session.get(Customer, customer_id)
        if not customer:
            return False, None, 0
        tier = customer.tier or "standard"
        limit = TIER_FEATURES.get(tier, TIER_FEATURES["standard"])["max_devices"]
        current = Device.query.filter_by(customer_id=customer_id).count()
        return (limit is not None and current >= limit), limit, current
    except Exception as exc:
        logger.warning("check_device_limit error: %s", exc)
        return False, None, 0


def tier_features(tier: str) -> dict:
    """Return feature set for a given tier."""
    return TIER_FEATURES.get(tier, TIER_FEATURES["standard"])
