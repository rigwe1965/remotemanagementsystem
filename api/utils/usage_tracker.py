"""API/token usage recording + spike detection for the superadmin-only usage monitor.

Every public function here fails open (catches everything, logs at debug/warning,
never raises) — a tracking bug must never break the feature it's instrumenting,
same philosophy as utils/rate_limit.py and utils/cache.py.
"""
import logging
import os
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# service -> {"input": $ per 1M input tokens, "output": $ per 1M output tokens}
_MODEL_PRICING = {
    os.getenv("AI_ASSISTANT_MODEL", "claude-haiku-4-5-20251001"): {
        "input": float(os.getenv("AI_ASSISTANT_COST_PER_1M_INPUT", "1.00")),
        "output": float(os.getenv("AI_ASSISTANT_COST_PER_1M_OUTPUT", "5.00")),
    },
}

_MIN_EVENTS_FOR_SIGNAL = 5  # ignore low-volume noise when computing spike multipliers
_KNOWN_SERVICES = (
    "ai_assistant", "ai_ticket_triage", "stripe", "psa_connectwise", "psa_autotask", "android_mdm",
    "email_imap", "network_scan", "webhook_slack", "webhook_teams", "webhook_generic", "smtp",
)


def _hourly_redis_key(dt: datetime) -> str:
    return f"rmm:usage:hourly:{dt.strftime('%Y%m%d%H')}"


def estimate_cost(model: str, input_tokens, output_tokens):
    pricing = _MODEL_PRICING.get(model)
    if not pricing:
        return None
    cost = 0.0
    if input_tokens:
        cost += (input_tokens / 1_000_000) * pricing["input"]
    if output_tokens:
        cost += (output_tokens / 1_000_000) * pricing["output"]
    return round(cost, 6)


def record_event(service, feature=None, user_id=None, input_tokens=None, output_tokens=None,
                  status="success", status_code=None, latency_ms=None, error=None, model=None):
    """Write one ApiUsageEvent row. Never raises."""
    try:
        from extensions import db
        from models.usage import ApiUsageEvent

        cost = None
        if input_tokens is not None or output_tokens is not None:
            cost = estimate_cost(model or os.getenv("AI_ASSISTANT_MODEL", ""), input_tokens, output_tokens)

        db.session.add(ApiUsageEvent(
            service=service,
            feature=(str(feature)[:100] if feature else None),
            user_id=user_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=cost,
            status=status,
            status_code=status_code,
            latency_ms=latency_ms,
            error_message=(str(error)[:500] if error else None),
        ))
        db.session.commit()
    except Exception as exc:
        logger.debug("record_event failed [%s/%s]: %s", service, feature, exc)
        try:
            from extensions import db
            db.session.rollback()
        except Exception:
            pass


def record_internal_api_call(endpoint, method, status_code, latency_ms):
    """Cheap Redis HINCRBY counter for internal Flask API request volume — too
    high-volume to write one DB row per request. Rolled into a durable Postgres
    table hourly by tasks.usage_tasks.persist_hourly_usage_rollup."""
    if not endpoint:
        return
    try:
        from utils.cache import _get_client
        client = _get_client()
        key = _hourly_redis_key(datetime.now(timezone.utc))
        field_base = f"{endpoint}|{method}"
        pipe = client.pipeline()
        pipe.hincrby(key, f"{field_base}|count", 1)
        if status_code and status_code >= 400:
            pipe.hincrby(key, f"{field_base}|errors", 1)
        pipe.hincrby(key, f"{field_base}|latency_sum", int(latency_ms or 0))
        pipe.expire(key, 8 * 86400)
        pipe.execute()
    except Exception as exc:
        logger.debug("record_internal_api_call failed [%s %s]: %s", method, endpoint, exc)


def _service_hour_count(service, hour_start, hour_end):
    from models.usage import ApiUsageEvent
    return ApiUsageEvent.query.filter(
        ApiUsageEvent.service == service,
        ApiUsageEvent.created_at >= hour_start,
        ApiUsageEvent.created_at < hour_end,
    ).count()


def _internal_api_hour_count(hour_start):
    from extensions import db
    from models.usage import ApiUsageHourly
    from sqlalchemy import func
    total = db.session.execute(
        db.select(func.sum(ApiUsageHourly.request_count)).where(ApiUsageHourly.bucket_start == hour_start)
    ).scalar()
    return total or 0


def compute_anomalies(spike_multiplier: float = 3.0):
    """Compare the most recently COMPLETED hour's usage per service against the
    trailing-7-day average for that same hour-of-day. Returns a list of dicts for
    any service exceeding spike_multiplier times its baseline. Read-only, cheap
    (bounded number of small queries), safe to call from both the API and a task."""
    out = []
    try:
        now = datetime.now(timezone.utc)
        current_hour_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        current_hour_end = current_hour_start + timedelta(hours=1)

        for service in _KNOWN_SERVICES:
            current = _service_hour_count(service, current_hour_start, current_hour_end)
            if current < _MIN_EVENTS_FOR_SIGNAL:
                continue
            samples = []
            for d in range(1, 8):
                start = current_hour_start - timedelta(days=d)
                end = start + timedelta(hours=1)
                samples.append(_service_hour_count(service, start, end))
            baseline = (sum(samples) / len(samples)) if samples else 0
            if baseline > 0 and current > baseline * spike_multiplier:
                out.append({
                    "service": service,
                    "current_hour_count": current,
                    "baseline_avg": round(baseline, 1),
                    "multiplier": round(current / baseline, 1),
                })

        # internal Flask API volume, from the durable hourly rollup table
        current_internal = _internal_api_hour_count(current_hour_start)
        if current_internal >= _MIN_EVENTS_FOR_SIGNAL:
            internal_samples = [
                _internal_api_hour_count(current_hour_start - timedelta(days=d)) for d in range(1, 8)
            ]
            baseline = (sum(internal_samples) / len(internal_samples)) if internal_samples else 0
            if baseline > 0 and current_internal > baseline * spike_multiplier:
                out.append({
                    "service": "internal_api",
                    "current_hour_count": current_internal,
                    "baseline_avg": round(baseline, 1),
                    "multiplier": round(current_internal / baseline, 1),
                })
    except Exception as exc:
        logger.warning("compute_anomalies failed: %s", exc)
    return out
