"""
AI Anomaly Detection — statistical baseline + z-score on device metrics.

Algorithm:
  1. For each online device, fetch last 24h of cpu_pct/ram_pct/disk_pct.
  2. Compute rolling mean + stddev over the oldest BASELINE_SAMPLES samples.
  3. If |value - mean| / stddev > Z_THRESHOLD for SPIKE_COUNT+ recent samples → alert.

No ML library required — pure statistics. Fast, explainable, zero training.
"""
import logging
from datetime import datetime, timezone, timedelta
from statistics import mean, stdev
from tasks.celery_app import celery
from services.device_query_service import online_devices

logger = logging.getLogger(__name__)

Z_THRESHOLD = 3.0       # standard deviations to flag as anomalous
SPIKE_COUNT = 3         # how many anomalous samples in 1h to fire an alert
MIN_SAMPLES = 10        # minimum samples needed to compute a baseline
BASELINE_SAMPLES = 20   # samples used for mean/stdev baseline

from tasks._app_singleton import get_app as _get_app



def _as_utc(dt):
    """SQLite returns naive datetimes for DateTime(timezone=True); treat them as UTC."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

def _zscore_anomalies(values: list[float]) -> list[bool]:
    """Return bool flags: True where z-score > Z_THRESHOLD."""
    if len(values) < MIN_SAMPLES:
        return [False] * len(values)
    baseline = values[:BASELINE_SAMPLES]
    mu = mean(baseline)
    try:
        sigma = stdev(baseline)
    except Exception:
        return [False] * len(values)
    if sigma < 0.01:
        return [False] * len(values)
    return [abs(v - mu) / sigma > Z_THRESHOLD for v in values]


def _fire_anomaly_alert(app, device, metric: str, value: float, z: float):
    """Create or update an open Alert for the detected anomaly.

    Anomaly alerts have no corresponding AlertRule (they're detected dynamically,
    not admin-configured), so rule_id stays unset. Dedup is keyed off the message
    prefix instead of a "rule_name" column — Alert has no such column, only
    rule_id/device_id/severity/status/message (see models/alert.py).
    """
    with app.app_context():
        from extensions import db
        from models.alert import Alert
        from utils.events import publish_event

        message_prefix = f"Anomaly: {metric} ="
        new_message = (
            f"Anomaly: {metric} = {value:.1f}% "
            f"({z:.1f}σ above 24h baseline)"
        )

        existing = Alert.query.filter(
            Alert.device_id == device.id,
            Alert.status == "open",
            Alert.message.like(f"{message_prefix}%"),
        ).first()

        if existing:
            existing.triggered_at = datetime.now(timezone.utc)
            existing.message = new_message
            db.session.commit()
            return

        alert = Alert(
            device_id=device.id,
            severity="warning",
            status="open",
            message=new_message,
            triggered_at=datetime.now(timezone.utc),
        )
        db.session.add(alert)
        db.session.commit()

        try:
            publish_event("alert_fired", {
                "device_id": device.id,
                "hostname": device.hostname,
                "metric": metric,
                "value": value,
                "z_score": round(z, 2),
                "severity": "warning",
                "source": "anomaly_detection",
            })
        except Exception:
            pass

        logger.info(
            "Anomaly alert fired: device=%s metric=%s value=%.1f z=%.2f",
            device.hostname, metric, value, z,
        )


@celery.task(name="tasks.anomaly_tasks.detect_metric_anomalies", bind=True, max_retries=2)
def detect_metric_anomalies(self):
    """
    Statistical anomaly detection across all online devices.
    Runs every 10 minutes via Celery beat.
    """
    app = _get_app()
    with app.app_context():
        from extensions import db
        from models.device import Device, DeviceMetrics

        devices = online_devices()
        if not devices:
            return

        cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)
        cutoff_1h = datetime.now(timezone.utc) - timedelta(hours=1)
        checked = 0
        fired = 0

        metric_fields = [
            ("cpu_pct", "CPU"),
            ("ram_pct", "RAM"),
            ("disk_pct", "Disk"),
        ]

        for device in devices:
            rows = (
                DeviceMetrics.query
                .filter(
                    DeviceMetrics.device_id == device.id,
                    DeviceMetrics.collected_at >= cutoff_24h,
                )
                .order_by(DeviceMetrics.collected_at.asc())
                .all()
            )
            if len(rows) < MIN_SAMPLES:
                continue

            checked += 1

            for field, label in metric_fields:
                values = [
                    getattr(r, field) for r in rows
                    if getattr(r, field) is not None
                ]
                if len(values) < MIN_SAMPLES:
                    continue

                flags = _zscore_anomalies(values)

                # Focus on recent 1h window
                recent_rows = [r for r in rows if _as_utc(r.collected_at) >= cutoff_1h]
                recent_values = [
                    getattr(r, field) for r in recent_rows
                    if getattr(r, field) is not None
                ]
                if not recent_values:
                    continue

                recent_flags = flags[-len(recent_values):]
                spike_count = sum(recent_flags)

                if spike_count >= SPIKE_COUNT:
                    worst = max(recent_values)
                    baseline = values[:BASELINE_SAMPLES]
                    mu = mean(baseline)
                    sigma = stdev(baseline) if len(baseline) > 1 else 1.0
                    z = abs(worst - mu) / max(sigma, 0.01)
                    _fire_anomaly_alert(app, device, label, worst, z)
                    fired += 1

        logger.info(
            "Anomaly scan done: %d devices checked, %d alerts fired",
            checked, fired,
        )
