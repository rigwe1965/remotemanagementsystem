import os
import sys
import platform
from pathlib import Path
from celery import Celery
from dotenv import load_dotenv

# Ensure api/ directory is in sys.path so all task imports find Flask app modules
_api_dir = str(Path(__file__).parent.parent)
if _api_dir not in sys.path:
    sys.path.insert(0, _api_dir)

load_dotenv()

# Sentry error tracking for the Celery worker/beat process — this module is the
# entrypoint when running `celery -A tasks.celery_app worker/beat`, which does not
# import api/app.py, so Sentry needs its own init here (no-op when SENTRY_DSN unset).
_sentry_dsn = os.getenv("SENTRY_DSN", "")
if _sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    sentry_sdk.init(
        dsn=_sentry_dsn,
        integrations=[CeleryIntegration()],
        traces_sample_rate=0.05,
        send_default_pii=False,
    )


def make_celery(app=None):
    celery = Celery(
        "rmm",
        broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
        backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
        include=[
            "tasks.alert_tasks",
            "tasks.patch_tasks",
            "tasks.script_tasks",
            "tasks.maintenance_tasks",
            "tasks.report_tasks",
            "tasks.automation_tasks",
            "tasks.network_tasks",
            "tasks.ticket_tasks",
            "tasks.email_tasks",
            "tasks.backup_tasks",
            "tasks.billing_tasks",
            "tasks.mqtt_tasks",
            "tasks.snmp_tasks",
            "tasks.anomaly_tasks",
            "tasks.psa_tasks",
            "tasks.mdm_tasks",
            "tasks.usage_tasks",
            "tasks.triage_tasks",
        ],
    )

    celery.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        worker_pool="solo" if platform.system() == "Windows" else "prefork",
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_default_retry_delay=60,
        task_max_retries=3,
        worker_prefetch_multiplier=1,
        beat_schedule={
            "evaluate-alert-rules-every-minute": {
                "task": "tasks.alert_tasks.evaluate_all_rules",
                "schedule": 60.0,
            },
            "mark-offline-devices-every-3-min": {
                "task": "tasks.alert_tasks.mark_offline_devices",
                "schedule": 180.0,
            },
            "sync-patch-status-every-30-min": {
                "task": "tasks.patch_tasks.sync_patch_status",
                "schedule": 1800.0,
            },
            "ping-agentless-devices-every-5-min": {
                "task": "tasks.network_tasks.ping_agentless_devices",
                "schedule": 300.0,
            },
            "unlock-expired-accounts-every-minute": {
                "task": "tasks.alert_tasks.unlock_expired_accounts",
                "schedule": 60.0,
            },
            "deactivate-dormant-accounts-daily": {
                "task": "tasks.alert_tasks.deactivate_dormant_accounts",
                "schedule": 86400.0,
            },
            "check-password-expiry-daily": {
                "task": "tasks.alert_tasks.check_password_expiry",
                "schedule": 86400.0,
            },
            "prune-old-data-daily": {
                "task": "tasks.maintenance_tasks.prune_old_data",
                "schedule": 86400.0,
            },
            "check-sla-breaches-hourly": {
                "task": "tasks.ticket_tasks.check_sla_breaches",
                "schedule": 3600.0,
            },
            "poll-support-inbox-every-minute": {
                "task": "tasks.email_tasks.poll_support_inbox",
                "schedule": 60.0,
            },
            "backup-database-daily": {
                "task": "tasks.backup_tasks.backup_database",
                "schedule": 86400.0,
            },
            "generate-recurring-invoices-daily": {
                "task": "tasks.billing_tasks.generate_recurring_invoices",
                "schedule": 86400.0,
            },
            "mqtt-sensor-poll-every-30s": {
                "task": "tasks.mqtt_tasks.subscribe_mqtt_sensors",
                "schedule": 30.0,
            },
            "snmp-device-poll-every-5min": {
                "task": "tasks.snmp_tasks.poll_snmp_devices",
                "schedule": 300.0,
            },
            "anomaly-detection-every-10min": {
                "task": "tasks.anomaly_tasks.detect_metric_anomalies",
                "schedule": 600.0,
            },
            "psa-sync-every-15min": {
                "task": "tasks.psa_tasks.sync_all_psa_integrations",
                "schedule": 900.0,
            },
            "mdm-sync-every-5-min": {
                "task": "tasks.mdm_tasks.sync_all_mdm_integrations",
                "schedule": 300.0,
            },
            "persist-usage-rollup-hourly": {
                "task": "tasks.usage_tasks.persist_hourly_usage_rollup",
                "schedule": 3600.0,
            },
            "detect-usage-anomaly-hourly": {
                "task": "tasks.usage_tasks.detect_usage_anomaly",
                "schedule": 3600.0,
            },
            "auto-close-ai-resolved-tickets-hourly": {
                "task": "tasks.triage_tasks.auto_close_resolved_tickets",
                "schedule": 3600.0,
            },
        },
    )

    if app is not None:
        class ContextTask(celery.Task):
            def __call__(self, *args, **kwargs):
                with app.app_context():
                    return self.run(*args, **kwargs)

        celery.Task = ContextTask

    return celery


# Standalone celery instance for worker startup
celery = make_celery()
