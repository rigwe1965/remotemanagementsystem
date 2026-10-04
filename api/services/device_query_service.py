"""Read-only device queries for the AI assistant's read tools."""
from datetime import datetime, timezone, timedelta
from sqlalchemy import func
from extensions import db
from models.device import Device, DeviceMetrics


def _batch_latest_metrics(device_ids: list) -> dict:
    if not device_ids:
        return {}
    subq = (
        db.select(func.max(DeviceMetrics.id).label("max_id"))
        .where(DeviceMetrics.device_id.in_(device_ids))
        .group_by(DeviceMetrics.device_id)
        .subquery()
    )
    rows = db.session.execute(
        db.select(DeviceMetrics).join(subq, DeviceMetrics.id == subq.c.max_id)
    ).scalars().all()
    return {m.device_id: m.to_dict() for m in rows}


def online_devices() -> list:
    """Devices currently marked online. Shared by alert/anomaly/automation Celery
    tasks that previously each hand-duplicated this exact filter — one place to
    change if "online" ever needs a soft-delete/staleness clause added."""
    return Device.query.filter_by(is_online=True).all()


def list_devices_for_assistant(actor_role: str, actor_customer_id: str, *,
                                is_online: bool = None, status: str = None,
                                platform: str = None, q: str = None, limit: int = 50) -> list:
    cid = actor_customer_id if actor_role == "client" else None
    query = Device.query
    if cid:
        query = query.filter_by(customer_id=cid)
    if is_online is not None:
        query = query.filter_by(is_online=is_online)
    if status:
        query = query.filter_by(status=status)
    if platform:
        platform = "mac" if platform.lower() in ("macos", "darwin") else platform.lower()
        query = query.filter_by(platform=platform)
    if q:
        query = query.filter(Device.hostname.ilike(f"%{q}%"))

    devices = query.order_by(Device.hostname).limit(min(limit, 100)).all()
    metrics_by_device = _batch_latest_metrics([d.id for d in devices])
    return [
        d.to_dict(include_latest_metrics=True, latest_metrics_data=metrics_by_device.get(d.id))
        for d in devices
    ]


def get_device_status_for_assistant(actor_role: str, actor_customer_id: str, device_id: str):
    """Returns (device_dict_or_None, error_or_None)."""
    device = db.session.get(Device, device_id)
    if not device:
        return None, ("Device not found", 404)
    if actor_role == "client" and device.customer_id != actor_customer_id:
        return None, ("Device not found", 404)
    metrics = _batch_latest_metrics([device.id])
    return device.to_dict(include_latest_metrics=True, latest_metrics_data=metrics.get(device.id)), None
