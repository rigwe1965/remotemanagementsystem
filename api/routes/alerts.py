import json
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from extensions import db
from models.alert import Alert, AlertRule
from utils.validation import validate_body
from utils.cache import cache_get_raw, cache_set_raw, cache_delete_pattern
from schemas.alerts import AlertRuleCreateSchema, AlertRuleUpdateSchema

alerts_bp = Blueprint("alerts", __name__)


def _require_role(*roles):
    claims = get_jwt()
    if claims.get("role") == "superadmin":
        return None
    if claims.get("role") not in roles:
        return jsonify({"error": "Insufficient permissions"}), 403
    return None


# --- Alert Rules ---

@alerts_bp.route("/alert_rules", methods=["GET"])
@jwt_required()
def list_rules():
    err = _require_role("admin", "technician", "viewer")
    if err:
        return err
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 200)
    customer_id = request.args.get("customer_id")
    query = AlertRule.query
    if customer_id:
        query = query.filter_by(customer_id=customer_id)
    paginated = query.order_by(AlertRule.name).paginate(page=page, per_page=per_page)
    return jsonify({
        "items": [r.to_dict() for r in paginated.items],
        "total": paginated.total,
        "page": page,
    }), 200


@alerts_bp.route("/alert_rules", methods=["POST"])
@jwt_required()
@validate_body(AlertRuleCreateSchema)
def create_rule():
    err = _require_role("admin", "technician")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if not data.get("name") or not data.get("metric") or not data.get("operator"):
        return jsonify({"error": "name, metric, operator required"}), 400
    rule = AlertRule(
        name=data["name"],
        customer_id=data.get("customer_id"),
        device_group_id=data.get("device_group_id"),
        metric=data["metric"],
        operator=data["operator"],
        threshold=data.get("threshold"),
        severity=data.get("severity", "warning"),
        cooldown_minutes=data.get("cooldown_minutes", 15),
        notification_channels=data.get("notification_channels", {}),
        auto_create_ticket=data.get("auto_create_ticket", False),
        is_active=data.get("is_active", True),
    )
    db.session.add(rule)
    db.session.commit()
    return jsonify(rule.to_dict()), 201


@alerts_bp.route("/alert_rules/<rule_id>", methods=["GET"])
@jwt_required()
def get_rule(rule_id):
    rule = db.get_or_404(AlertRule, rule_id)
    return jsonify(rule.to_dict()), 200


@alerts_bp.route("/alert_rules/<rule_id>", methods=["PUT"])
@jwt_required()
@validate_body(AlertRuleUpdateSchema)
def update_rule(rule_id):
    err = _require_role("admin", "technician")
    if err:
        return err
    rule = db.get_or_404(AlertRule, rule_id)
    data = request.get_json(silent=True) or {}
    for field in ["name", "metric", "operator", "threshold", "severity",
                  "cooldown_minutes", "notification_channels", "auto_create_ticket", "is_active"]:
        if field in data:
            setattr(rule, field, data[field])
    db.session.commit()
    return jsonify(rule.to_dict()), 200


@alerts_bp.route("/alert_rules/<rule_id>", methods=["DELETE"])
@jwt_required()
def delete_rule(rule_id):
    err = _require_role("admin")
    if err:
        return err
    rule = db.get_or_404(AlertRule, rule_id)
    db.session.delete(rule)
    db.session.commit()
    return jsonify({"message": "Rule deleted"}), 200


# --- Active Alerts ---

@alerts_bp.route("/alerts", methods=["GET"])
@jwt_required()
def list_alerts():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 200)
    status = request.args.get("status")
    severity = request.args.get("severity")
    device_id = request.args.get("device_id")

    _ck = f"rmm:alerts:list:p{page}:pp{per_page}:s{status or ''}:sv{severity or ''}:d{device_id or ''}"
    raw = cache_get_raw(_ck)
    if raw:
        return Response(raw, mimetype="application/json")

    query = Alert.query
    if status:
        query = query.filter_by(status=status)
    if severity:
        query = query.filter_by(severity=severity)
    if device_id:
        query = query.filter_by(device_id=device_id)

    paginated = query.order_by(Alert.triggered_at.desc()).paginate(page=page, per_page=per_page)
    result = {
        "items": [a.to_dict() for a in paginated.items],
        "total": paginated.total,
        "page": page,
    }
    raw_json = json.dumps(result, default=str)
    cache_set_raw(_ck, raw_json, 20)
    return Response(raw_json, mimetype="application/json")


@alerts_bp.route("/alerts/<alert_id>/acknowledge", methods=["POST"])
@jwt_required()
def acknowledge_alert(alert_id):
    alert = db.get_or_404(Alert, alert_id)
    alert.status = "acknowledged"
    alert.acknowledged_by = get_jwt_identity()
    alert.acknowledged_at = datetime.now(timezone.utc)
    db.session.commit()
    cache_delete_pattern("rmm:alerts:list:*")
    return jsonify(alert.to_dict()), 200


@alerts_bp.route("/alerts/<alert_id>/resolve", methods=["POST"])
@jwt_required()
def resolve_alert(alert_id):
    alert = db.get_or_404(Alert, alert_id)
    alert.status = "resolved"
    alert.resolved_at = datetime.now(timezone.utc)
    db.session.commit()
    cache_delete_pattern("rmm:alerts:list:*")
    return jsonify(alert.to_dict()), 200
