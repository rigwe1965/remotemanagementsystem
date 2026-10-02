"""MDM sync Celery tasks — reconciles Android Management API device state into
local Device/MobileEnrollment rows. Same fan-out shape as psa_tasks.py."""
import logging
from datetime import datetime, timezone

from tasks.celery_app import celery

logger = logging.getLogger(__name__)

from tasks._app_singleton import get_app as _get_app
from tasks._sync_circuit_breaker import record_failure_and_retry


@celery.task(name="tasks.mdm_tasks.sync_all_mdm_integrations", bind=True, max_retries=1)
def sync_all_mdm_integrations(self):
    """Fan-out: dispatch one sync task per active, bound MDM integration."""
    from sqlalchemy.exc import OperationalError

    app = _get_app()
    with app.app_context():
        from models.mdm_integration import MdmIntegration
        try:
            active = MdmIntegration.query.filter(
                MdmIntegration.is_active == True,  # noqa: E712
                MdmIntegration.enterprise_id.isnot(None),
            ).all()
            for integration in active:
                sync_mdm_integration.delay(integration.id)
            logger.info("MDM sync: dispatched %d integration(s)", len(active))
        except OperationalError as exc:
            raise self.retry(exc=exc, countdown=120)


@celery.task(name="tasks.mdm_tasks.sync_mdm_integration", bind=True, max_retries=2)
def sync_mdm_integration(self, mdm_integration_id: str):
    """Pull enterprises.devices.list, update Device + MobileEnrollment rows."""
    app = _get_app()
    with app.app_context():
        from extensions import db
        from models.mdm_integration import MdmIntegration, MobileEnrollment
        from models.device import Device

        integration = db.session.get(MdmIntegration, mdm_integration_id)
        if not integration or not integration.is_active or not integration.enterprise_id:
            return

        try:
            client = integration.get_client()
            remote_devices = client.list_devices()

            pending_by_token = {
                e.enrollment_token: e
                for e in MobileEnrollment.query.filter_by(
                    mdm_integration_id=integration.id, status="pending",
                ).all()
                if e.enrollment_token
            }
            enrolled_by_name = {
                e.android_enterprise_device_name: e
                for e in MobileEnrollment.query.filter_by(
                    mdm_integration_id=integration.id, status="enrolled",
                ).all()
                if e.android_enterprise_device_name
            }

            now = datetime.now(timezone.utc)
            seen_names = set()

            for rd in remote_devices:
                name = rd.get("name")
                seen_names.add(name)
                enrollment = enrolled_by_name.get(name)

                if not enrollment:
                    # First time we've seen this device — match it to a pending
                    # enrollment (Android doesn't echo the enrollment token back,
                    # so any single still-pending enrollment for this integration
                    # is our best-effort match) or skip if none pending.
                    enrollment = next(iter(pending_by_token.values()), None)
                    if not enrollment:
                        continue
                    pending_by_token.pop(enrollment.enrollment_token, None)
                    enrollment.android_enterprise_device_name = name
                    enrollment.status = "enrolled"

                    device = Device(
                        customer_id=enrollment.customer_id,
                        hostname=rd.get("hardwareInfo", {}).get("model", "Android device"),
                        display_name=rd.get("hardwareInfo", {}).get("model"),
                        platform="android",
                        device_type="mobile",
                        is_agentless=True,
                        is_online=True,
                    )
                    db.session.add(device)
                    db.session.flush()
                    enrollment.device_id = device.id

                device = db.session.get(Device, enrollment.device_id) if enrollment.device_id else None
                hw = rd.get("hardwareInfo", {}) or {}
                sw = rd.get("softwareInfo", {}) or {}
                if device:
                    device.is_online = True
                    device.last_seen = now
                    device.os_name = "Android"
                    device.os_version = sw.get("androidVersion")
                    device.vendor = hw.get("brand") or hw.get("manufacturer")
                    if hw.get("model"):
                        device.display_name = device.display_name or hw["model"]

                enrollment.last_status_report_at = now
                enrollment.policy_compliant = rd.get("policyCompliant")
                enrollment.non_compliance_details = rd.get("nonComplianceDetails")

            db.session.commit()

            integration.last_sync_at = now
            integration.sync_error = None
            integration.consecutive_failures = 0
            db.session.commit()
            logger.info("MDM sync complete: %s (%d devices)", integration.name, len(remote_devices))

        except Exception as exc:
            record_failure_and_retry(self, integration, exc, label="MDM", logger=logger)
