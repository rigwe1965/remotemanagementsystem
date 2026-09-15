"""
Periodic tasks: evaluate alert rules against latest device metrics,
mark devices offline if heartbeat timeout exceeded.
"""
import logging
import os
from datetime import datetime, timezone, timedelta
from tasks.celery_app import celery
from sqlalchemy import func

logger = logging.getLogger(__name__)

SENSOR_METRICS = {
    "temperature", "humidity", "co2", "pm25", "voc",
    "motion", "door", "power_watts", "ups_battery", "ups_load",
}

_EVAL_LOCK_KEY = "rmm:alert_eval:lock"
_EVAL_LOCK_TTL = 55  # seconds — expires just before next 60s beat fires

# Shared Flask app — created once per worker process, not once per task
_app = None


def _get_app():
    global _app
    if _app is None:
        from app import create_app
        _app = create_app()
    return _app


def _get_redis():
    import redis
    return redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        socket_timeout=2,
        socket_connect_timeout=2,
    )


@celery.task(name="tasks.alert_tasks.evaluate_all_rules", bind=True, max_retries=3)
def evaluate_all_rules(self):
    # Redis lock — prevent thundering herd when evaluation takes longer than 60s beat interval
    try:
        _r = _get_redis()
        acquired = _r.set(_EVAL_LOCK_KEY, "1", nx=True, ex=_EVAL_LOCK_TTL)
        if not acquired:
            logger.info("evaluate_all_rules: skipping — previous run still in progress")
            return
    except Exception as exc:
        logger.warning("evaluate_all_rules: could not acquire lock (%s) — running without it", exc)
        _r = None

    from extensions import db
    from models.alert import AlertRule, Alert
    from models.device import Device, DeviceMetrics
    from sqlalchemy.exc import OperationalError

    app = _get_app()
    with app.app_context():
        try:
            rules = AlertRule.query.filter_by(is_active=True).all()
            if not rules:
                return

            now = datetime.now(timezone.utc)

            # Collect all online devices across all rules in one query
            all_online_devices = Device.query.filter_by(is_online=True).all()
            if not all_online_devices:
                return

            all_device_ids = [d.id for d in all_online_devices]
            devices_by_id = {d.id: d for d in all_online_devices}

            # Batch-load latest metrics for ALL online devices — one query total
            max_id_subq = (
                db.select(func.max(DeviceMetrics.id).label("max_id"))
                .where(DeviceMetrics.device_id.in_(all_device_ids))
                .group_by(DeviceMetrics.device_id)
                .subquery()
            )
            latest_metrics_by_device = {
                m.device_id: m
                for m in DeviceMetrics.query.join(
                    max_id_subq, DeviceMetrics.id == max_id_subq.c.max_id
                ).all()
            }

            # ALL open/acknowledged alerts — used for deduplication (no time filter)
            open_alerts = Alert.query.filter(
                Alert.device_id.in_(all_device_ids),
                Alert.status.in_(["open", "acknowledged"]),
            ).all()
            open_alert_map = {(a.rule_id, a.device_id): a for a in open_alerts}

            # Recently resolved alerts — used for cooldown check after recovery
            max_cooldown = max((r.cooldown_minutes for r in rules), default=15)
            cooldown_since = now - timedelta(minutes=max_cooldown)
            resolved_alerts = Alert.query.filter(
                Alert.device_id.in_(all_device_ids),
                Alert.status == "resolved",
                Alert.resolved_at >= cooldown_since,
            ).all()
            resolved_alert_map = {(a.rule_id, a.device_id): a for a in resolved_alerts}

            # Track which (rule_id, device_id) pairs need auto-resolve
            to_resolve_keys = []  # list of (rule_id, device_id)

            for rule in rules:
                # Filter devices for this rule
                if rule.device_group_id:
                    devices = [d for d in all_online_devices if d.group_id == rule.device_group_id]
                elif rule.customer_id:
                    devices = [d for d in all_online_devices if d.customer_id == rule.customer_id]
                else:
                    devices = all_online_devices

                if not devices:
                    continue

                rule_cooldown_since = now - timedelta(minutes=rule.cooldown_minutes)

                rule_cooldown_since = now - timedelta(minutes=rule.cooldown_minutes)

                for device in devices:
                    if rule.metric in SENSOR_METRICS:
                        metric_val = _get_latest_sensor_value(device.id, rule.metric)
                    else:
                        latest = latest_metrics_by_device.get(device.id)
                        if not latest:
                            continue
                        metric_val = _get_metric_value(latest, rule.metric)

                    if metric_val is None:
                        continue

                    triggered = _evaluate(metric_val, rule.operator, rule.threshold)
                    key = (rule.id, device.id)

                    if not triggered:
                        if key in open_alert_map:
                            to_resolve_keys.append(key)
                        continue

                    # Already open — don't storm
                    if key in open_alert_map:
                        continue

                    # Respect cooldown after last resolve
                    resolved = resolved_alert_map.get(key)
                    if resolved and resolved.resolved_at and resolved.resolved_at >= rule_cooldown_since:
                        continue

                    # Create alert
                    alert = Alert(
                        rule_id=rule.id,
                        device_id=device.id,
                        severity=rule.severity,
                        message=f"{rule.name}: {rule.metric} is {metric_val:.1f} (threshold {rule.threshold})",
                    )
                    db.session.add(alert)

                    if rule.auto_create_ticket:
                        from models.ticket import Ticket
                        ticket = Ticket(
                            title=f"[AUTO] {rule.name} on {device.hostname}",
                            description=alert.message,
                            customer_id=device.customer_id,
                            device_id=device.id,
                            priority="critical" if rule.severity == "critical" else "high",
                            source="alert",
                        )
                        db.session.add(ticket)

                    channels = rule.notification_channels or {}
                    emails = channels.get("email", [])
                    if emails:
                        from utils.notifications import send_alert_notification
                        send_alert_notification(rule.name, device.hostname, alert.message, emails)
                    if any(channels.get(k) for k in ("slack", "teams", "webhook")):
                        from utils.webhook import dispatch_alert_webhooks
                        dispatch_alert_webhooks(
                            channels, rule.name, device.hostname,
                            alert.message, rule.severity,
                        )

                    try:
                        from utils.events import publish_event
                        publish_event("new_alert", {
                            "rule": rule.name,
                            "device": device.hostname,
                            "severity": rule.severity,
                            "message": alert.message,
                        })
                    except Exception:
                        pass

            # Bulk auto-resolve in one UPDATE per (rule_id, device_id) batch
            if to_resolve_keys:
                for rule_id, device_id in to_resolve_keys:
                    Alert.query.filter(
                        Alert.rule_id == rule_id,
                        Alert.device_id == device_id,
                        Alert.status == "open",
                    ).update({"status": "resolved", "resolved_at": now}, synchronize_session=False)

            db.session.commit()

        except OperationalError as exc:
            db.session.rollback()
            raise self.retry(exc=exc, countdown=30)
        except Exception:
            db.session.rollback()
            logger.exception("evaluate_all_rules failed")
            raise
        finally:
            try:
                if _r is not None:
                    _r.delete(_EVAL_LOCK_KEY)
            except Exception:
                pass


@celery.task(name="tasks.alert_tasks.mark_offline_devices", bind=True, max_retries=3)
def mark_offline_devices(self):
    from extensions import db
    from models.device import Device
    from models.alert import AlertRule, Alert
    from sqlalchemy.exc import OperationalError
    from sqlalchemy import update as sa_update

    app = _get_app()
    with app.app_context():
        try:
            threshold = datetime.now(timezone.utc) - timedelta(minutes=3)

            # Bulk UPDATE — no Python-side loop, no ORM object loading
            result = db.session.execute(
                sa_update(Device)
                .where(Device.is_online == True, Device.last_seen < threshold)
                .values(is_online=False, status="offline")
                .returning(Device.id, Device.hostname, Device.customer_id, Device.last_seen)
            )
            stale_rows = result.fetchall()

            if not stale_rows:
                db.session.commit()
                return 0

            offline_rule = AlertRule.query.filter_by(metric="offline", is_active=True).first()
            stale_ids = [r[0] for r in stale_rows]

            if offline_rule:
                # Batch-check existing open offline alerts — one query
                existing_offline = {
                    a.device_id
                    for a in Alert.query.filter(
                        Alert.device_id.in_(stale_ids),
                        Alert.rule_id == offline_rule.id,
                        Alert.status == "open",
                    ).all()
                }

                for device_id, hostname, customer_id, last_seen in stale_rows:
                    if device_id in existing_offline:
                        continue
                    last_seen_str = (
                        last_seen.strftime("%Y-%m-%d %H:%M UTC") if last_seen else "unknown"
                    )
                    db.session.add(Alert(
                        rule_id=offline_rule.id,
                        device_id=device_id,
                        severity="critical",
                        message=f"{hostname} has gone offline (last seen: {last_seen_str})",
                    ))

            try:
                from utils.events import publish_event
                for device_id, hostname, _, _ in stale_rows:
                    publish_event("device_offline", {"device_id": device_id, "hostname": hostname})
            except Exception:
                pass

            db.session.commit()
            return len(stale_rows)

        except OperationalError as exc:
            db.session.rollback()
            raise self.retry(exc=exc, countdown=30)
        except Exception:
            db.session.rollback()
            logger.exception("mark_offline_devices failed")
            raise


def _get_metric_value(metrics, metric_name: str):
    mapping = {
        "cpu": metrics.cpu_pct,
        "ram": metrics.ram_pct,
        "disk": metrics.disk_pct,
        "battery": metrics.battery_pct,
    }
    return mapping.get(metric_name)


def _get_latest_sensor_value(device_id: str, sensor_type: str):
    """Return most recent sensor reading value within last 10 minutes, or None."""
    from models.device import DeviceSensorReading
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
    reading = (
        DeviceSensorReading.query
        .filter(
            DeviceSensorReading.device_id == device_id,
            DeviceSensorReading.sensor_type == sensor_type,
            DeviceSensorReading.collected_at >= cutoff,
        )
        .order_by(DeviceSensorReading.collected_at.desc())
        .first()
    )
    return reading.value if reading else None


def _evaluate(value, operator: str, threshold: float) -> bool:
    if threshold is None:
        return False
    ops = {
        "gt": value > threshold,
        "gte": value >= threshold,
        "lt": value < threshold,
        "lte": value <= threshold,
        "eq": abs(value - threshold) < 0.01,
    }
    return ops.get(operator, False)


@celery.task(name="tasks.alert_tasks.unlock_expired_accounts", bind=True, max_retries=3)
def unlock_expired_accounts(self):
    from extensions import db
    from models.user import User
    from sqlalchemy.exc import OperationalError

    app = _get_app()
    with app.app_context():
        try:
            now = datetime.now(timezone.utc)
            expired = User.query.filter(
                User.is_locked == True,
                User.locked_until != None,
                User.locked_until <= now,
            ).all()

            for user in expired:
                user.is_locked = False
                user.locked_until = None
                user.failed_login_attempts = 0
                logger.info("Auto-unlocked account: %s (lockout expired)", user.email)

            if expired:
                db.session.commit()
                logger.info("unlock_expired_accounts: unlocked %d account(s)", len(expired))

            return len(expired)

        except OperationalError as exc:
            db.session.rollback()
            raise self.retry(exc=exc, countdown=30)
        except Exception:
            db.session.rollback()
            logger.exception("unlock_expired_accounts failed")
            raise


@celery.task(name="tasks.alert_tasks.deactivate_dormant_accounts", bind=True, max_retries=3)
def deactivate_dormant_accounts(self):
    from extensions import db
    from models.user import User
    from models.audit import AuditLog
    from sqlalchemy.exc import OperationalError
    from utils.notifications import send_account_deactivated_email, send_dormant_admin_alert

    app = _get_app()
    with app.app_context():
        try:
            now = datetime.now(timezone.utc)
            threshold = now - timedelta(days=60)

            dormant = User.query.filter(
                User.is_active == True,
                User.role != "superadmin",
                db.or_(
                    User.last_login < threshold,
                    db.and_(User.last_login == None, User.created_at < threshold),
                ),
            ).all()

            deactivated = []
            for user in dormant:
                user.is_active = False
                db.session.add(AuditLog(
                    user_id=None,
                    action="AUTO_DEACTIVATE_DORMANT",
                    resource_type="user",
                    resource_id=user.id,
                    payload={"email": user.email, "last_login": user.last_login.isoformat() if user.last_login else None},
                ))
                send_account_deactivated_email(user.email)
                deactivated.append(user.email)
                logger.info("Auto-deactivated dormant account: %s", user.email)

            if deactivated:
                admin_emails = [
                    u.email for u in User.query.filter(
                        User.role == "admin", User.is_active == True
                    ).all()
                ]
                send_dormant_admin_alert(deactivated, admin_emails)
                db.session.commit()
                logger.info("deactivate_dormant_accounts: deactivated %d account(s)", len(deactivated))

            return len(deactivated)

        except OperationalError as exc:
            db.session.rollback()
            raise self.retry(exc=exc, countdown=60)
        except Exception:
            db.session.rollback()
            logger.exception("deactivate_dormant_accounts failed")
            raise


@celery.task(name="tasks.alert_tasks.check_password_expiry", bind=True, max_retries=3)
def check_password_expiry(self):
    from extensions import db
    from models.user import User
    from sqlalchemy.exc import OperationalError
    from utils.notifications import send_password_expiry_warning

    app = _get_app()
    with app.app_context():
        try:
            now = datetime.now(timezone.utc)
            warning_floor = now - timedelta(days=89)
            warning_ceil  = now - timedelta(days=83)

            warning_users = User.query.filter(
                User.is_active == True,
                User.role != "superadmin",
                User.password_changed_at != None,
                User.password_changed_at <= warning_ceil,
                User.password_changed_at >= warning_floor,
                User.must_change_password == False,
            ).all()

            for user in warning_users:
                days_left = 90 - (now - user.password_changed_at).days
                send_password_expiry_warning(user.email, max(1, days_left))
                logger.info("Password expiry warning sent: %s (%d days left)", user.email, days_left)

            return len(warning_users)

        except OperationalError as exc:
            db.session.rollback()
            raise self.retry(exc=exc, countdown=60)
        except Exception:
            db.session.rollback()
            logger.exception("check_password_expiry failed")
            raise
