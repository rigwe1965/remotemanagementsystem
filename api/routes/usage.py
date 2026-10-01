"""API & Token Usage Monitoring — admin and superadmin only.

Restricted to admin/superadmin — technician, viewer, and client roles get 403.
"""
import logging
from datetime import datetime, timezone, timedelta

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt

from extensions import db
from models.usage import ApiUsageEvent, ApiUsageHourly, UsageAlertConfig
from utils.usage_tracker import compute_anomalies

log = logging.getLogger(__name__)

usage_bp = Blueprint("usage", __name__)

_RANGES = {"today": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}


def _require_admin():
    if get_jwt().get("role") not in ("admin", "superadmin"):
        return jsonify({"error": "Administrator access required"}), 403
    return None


def _range_start(range_key: str) -> datetime:
    delta = _RANGES.get(range_key, _RANGES["7d"])
    return datetime.now(timezone.utc) - delta


@usage_bp.route("/summary", methods=["GET"])
@jwt_required()
def summary():
    err = _require_admin()
    if err:
        return err

    range_key = request.args.get("range", "7d")
    start = _range_start(range_key)

    from sqlalchemy import func, case
    rows = db.session.execute(
        db.select(
            ApiUsageEvent.service,
            func.count().label("calls"),
            func.sum(ApiUsageEvent.input_tokens).label("input_tokens"),
            func.sum(ApiUsageEvent.output_tokens).label("output_tokens"),
            func.sum(ApiUsageEvent.estimated_cost_usd).label("cost"),
            func.sum(case((ApiUsageEvent.status != "success", 1), else_=0)).label("errors"),
        ).where(ApiUsageEvent.created_at >= start).group_by(ApiUsageEvent.service)
    ).all()

    services = []
    total_calls = 0
    total_tokens = 0
    total_cost = 0.0
    total_errors = 0
    for r in rows:
        calls = r.calls or 0
        tokens = (r.input_tokens or 0) + (r.output_tokens or 0)
        cost = float(r.cost or 0)
        errors = r.errors or 0
        total_calls += calls
        total_tokens += tokens
        total_cost += cost
        total_errors += errors
        services.append({
            "service": r.service,
            "calls": calls,
            "input_tokens": r.input_tokens or 0,
            "output_tokens": r.output_tokens or 0,
            "estimated_cost_usd": round(cost, 4),
            "error_count": errors,
            "error_rate": round(errors / calls, 3) if calls else 0,
        })

    internal_total = db.session.execute(
        db.select(func.sum(ApiUsageHourly.request_count)).where(ApiUsageHourly.bucket_start >= start)
    ).scalar() or 0
    internal_errors = db.session.execute(
        db.select(func.sum(ApiUsageHourly.error_count)).where(ApiUsageHourly.bucket_start >= start)
    ).scalar() or 0
    if internal_total:
        services.append({
            "service": "internal_api",
            "calls": internal_total,
            "input_tokens": 0,
            "output_tokens": 0,
            "estimated_cost_usd": 0,
            "error_count": internal_errors,
            "error_rate": round(internal_errors / internal_total, 3) if internal_total else 0,
        })
        total_calls += internal_total
        total_errors += internal_errors

    cfg = UsageAlertConfig.get_or_create()
    anomalies = compute_anomalies(cfg.spike_multiplier) if cfg.is_enabled else compute_anomalies()

    return jsonify({
        "range": range_key,
        "services": sorted(services, key=lambda s: s["calls"], reverse=True),
        "totals": {
            "calls": total_calls,
            "tokens": total_tokens,
            "estimated_cost_usd": round(total_cost, 4),
            "error_count": total_errors,
            "error_rate": round(total_errors / total_calls, 3) if total_calls else 0,
        },
        "anomalies": anomalies,
    }), 200


@usage_bp.route("/timeseries", methods=["GET"])
@jwt_required()
def timeseries():
    err = _require_admin()
    if err:
        return err

    range_key = request.args.get("range", "7d")
    service = request.args.get("service")
    metric = request.args.get("metric", "calls")
    start = _range_start(range_key)

    from sqlalchemy import func
    bucket_fmt = "%Y-%m-%d %H:00" if range_key == "today" else "%Y-%m-%d"
    bucket_expr = func.strftime(bucket_fmt, ApiUsageEvent.created_at) \
        if db.engine.dialect.name == "sqlite" else func.to_char(ApiUsageEvent.created_at, "YYYY-MM-DD HH24:00" if range_key == "today" else "YYYY-MM-DD")

    q = db.select(
        bucket_expr.label("bucket"),
        func.count().label("calls"),
        func.sum(ApiUsageEvent.input_tokens).label("input_tokens"),
        func.sum(ApiUsageEvent.output_tokens).label("output_tokens"),
        func.sum(ApiUsageEvent.estimated_cost_usd).label("cost"),
    ).where(ApiUsageEvent.created_at >= start)
    if service:
        q = q.where(ApiUsageEvent.service == service)
    q = q.group_by("bucket").order_by("bucket")

    rows = db.session.execute(q).all()
    points = []
    for r in rows:
        if metric == "tokens":
            value = (r.input_tokens or 0) + (r.output_tokens or 0)
        elif metric == "cost":
            value = round(float(r.cost or 0), 4)
        else:
            value = r.calls or 0
        points.append({"bucket": r.bucket, "value": value})

    return jsonify({"range": range_key, "service": service, "metric": metric, "points": points}), 200


@usage_bp.route("/by-feature", methods=["GET"])
@jwt_required()
def by_feature():
    err = _require_admin()
    if err:
        return err

    range_key = request.args.get("range", "7d")
    service = request.args.get("service")
    start = _range_start(range_key)

    from sqlalchemy import func
    q = db.select(
        ApiUsageEvent.service,
        ApiUsageEvent.feature,
        ApiUsageEvent.user_id,
        func.count().label("calls"),
        func.sum(ApiUsageEvent.input_tokens).label("input_tokens"),
        func.sum(ApiUsageEvent.output_tokens).label("output_tokens"),
        func.sum(ApiUsageEvent.estimated_cost_usd).label("cost"),
    ).where(ApiUsageEvent.created_at >= start)
    if service:
        q = q.where(ApiUsageEvent.service == service)
    q = q.group_by(ApiUsageEvent.service, ApiUsageEvent.feature, ApiUsageEvent.user_id) \
         .order_by(func.count().desc()).limit(50)

    rows = db.session.execute(q).all()

    user_ids = {r.user_id for r in rows if r.user_id}
    emails = {}
    if user_ids:
        from models.user import User
        for u in User.query.filter(User.id.in_(user_ids)).all():
            emails[u.id] = u.email

    items = [{
        "service": r.service,
        "feature": r.feature,
        "user_id": r.user_id,
        "user_email": emails.get(r.user_id),
        "calls": r.calls or 0,
        "input_tokens": r.input_tokens or 0,
        "output_tokens": r.output_tokens or 0,
        "estimated_cost_usd": round(float(r.cost or 0), 4),
    } for r in rows]

    return jsonify({"range": range_key, "items": items}), 200


@usage_bp.route("/events", methods=["GET"])
@jwt_required()
def events():
    err = _require_admin()
    if err:
        return err

    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 200)
    service = request.args.get("service")
    status = request.args.get("status")

    q = ApiUsageEvent.query
    if service:
        q = q.filter_by(service=service)
    if status:
        q = q.filter_by(status=status)

    paginated = q.order_by(ApiUsageEvent.created_at.desc()).paginate(page=page, per_page=per_page)
    return jsonify({
        "items": [e.to_dict() for e in paginated.items],
        "total": paginated.total,
        "page": page,
        "per_page": per_page,
        "pages": paginated.pages,
    }), 200


@usage_bp.route("/alert-config", methods=["GET"])
@jwt_required()
def get_alert_config():
    err = _require_admin()
    if err:
        return err
    return jsonify(UsageAlertConfig.get_or_create().to_dict()), 200


@usage_bp.route("/alert-config", methods=["PUT"])
@jwt_required()
def update_alert_config():
    err = _require_admin()
    if err:
        return err

    body = request.get_json(silent=True) or {}
    cfg = UsageAlertConfig.get_or_create()

    if "is_enabled" in body:
        cfg.is_enabled = bool(body["is_enabled"])
    if "spike_multiplier" in body:
        try:
            cfg.spike_multiplier = max(1.5, float(body["spike_multiplier"]))
        except (TypeError, ValueError):
            return jsonify({"error": "spike_multiplier must be a number"}), 400
    if "notification_channels" in body and isinstance(body["notification_channels"], dict):
        cfg.notification_channels = body["notification_channels"]

    from flask_jwt_extended import get_jwt_identity
    cfg.updated_by = get_jwt_identity()
    db.session.commit()
    return jsonify(cfg.to_dict()), 200
