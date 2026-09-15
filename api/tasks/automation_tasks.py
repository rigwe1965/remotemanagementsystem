"""
Automation profile execution task.
Runs asynchronously so the HTTP request returns immediately.
"""
import logging
from datetime import datetime, timezone
from tasks.celery_app import celery

logger = logging.getLogger(__name__)

_app = None


def _get_app():
    global _app
    if _app is None:
        from app import create_app
        _app = create_app()
    return _app


@celery.task(name="tasks.automation_tasks.enqueue_profile_run", bind=True, max_retries=3)
def enqueue_profile_run(self, profile_id: str):
    from extensions import db
    from models.automation import AutomationProfile, ScheduledTaskRun
    from models.device import Device
    from sqlalchemy.exc import OperationalError

    with _get_app().app_context():
        try:
            profile = db.session.get(AutomationProfile, profile_id)
            if not profile:
                logger.warning("enqueue_profile_run: profile %s not found", profile_id)
                return

            # Resolve target devices
            if profile.device_group_id:
                devices = Device.query.filter_by(
                    group_id=profile.device_group_id, is_online=True
                ).all()
            elif profile.customer_id:
                devices = Device.query.filter_by(
                    customer_id=profile.customer_id, is_online=True
                ).all()
            else:
                devices = Device.query.filter_by(is_online=True).all()

            if not devices:
                logger.info("enqueue_profile_run: no online devices for profile %s", profile_id)
                return

            from models.script import Script, ScriptRun

            for device in devices:
                run = ScheduledTaskRun(
                    profile_id=profile_id,
                    device_id=device.id,
                    status="queued",
                )
                db.session.add(run)
                _dispatch_profile_tasks(profile, device.id, db)

            profile.last_run_at = datetime.now(timezone.utc)
            db.session.commit()
            logger.info(
                "enqueue_profile_run: queued %d devices for profile %s",
                len(devices), profile_id,
            )

        except OperationalError as exc:
            db.session.rollback()
            raise self.retry(exc=exc, countdown=30)
        except Exception:
            db.session.rollback()
            logger.exception("enqueue_profile_run failed for profile %s", profile_id)
            raise


def _dispatch_profile_tasks(profile, device_id: str, db_session) -> None:
    """Create ScriptRun records for each enabled task in a profile config."""
    from models.script import ScriptRun
    from utils.builtin_scripts import get_builtin_script_id

    task_map = []

    disk = profile.disk_config or {}
    if disk.get("defrag"):
        task_map.append("defrag")
    if disk.get("checkdisk"):
        task_map.append("check_disk")

    maint = profile.maintenance_config or {}
    if maint.get("delete_temp"):
        task_map.append("clean_temp")
    if maint.get("restore_point"):
        task_map.append("restore_point")
    if maint.get("clear_history"):
        task_map.append("clear_browser")
    if maint.get("reboot"):
        task_map.append("reboot")
    if maint.get("shutdown"):
        task_map.append("shutdown")

    for task_type in task_map:
        script_id = get_builtin_script_id(task_type)
        if script_id:
            run = ScriptRun(
                script_id=script_id,
                device_id=device_id,
                timeout_seconds=300,
            )
            db_session.session.add(run)

    # Attach any explicitly configured scripts
    for script_id in (profile.scripts or []):
        run = ScriptRun(
            script_id=script_id,
            device_id=device_id,
            timeout_seconds=300,
        )
        db_session.session.add(run)
