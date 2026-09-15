"""Report generation task — Phase 9."""
import csv
import io
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from tasks.celery_app import celery

logger = logging.getLogger(__name__)

REPORTS_DIR = Path(__file__).parent.parent / "reports"

_app = None


def _get_app():
    global _app
    if _app is None:
        from app import create_app
        _app = create_app()
    return _app


def _ensure_reports_dir():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


@celery.task(name="tasks.report_tasks.generate_report", bind=True, max_retries=2)
def generate_report(self, report_id: str):
    """Generate a CSV report and store file path on the Report record."""
    from extensions import db
    from models.report import Report
    from sqlalchemy.exc import OperationalError

    with _get_app().app_context():
        try:
            report = db.session.get(Report, report_id)
            if not report:
                logger.warning("generate_report: report %s not found", report_id)
                return

            _ensure_reports_dir()
            rows, headers = _collect_data(report)

            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            safe_type = report.template_type.replace(" ", "_")
            filename = f"{safe_type}_{ts}.csv"
            filepath = REPORTS_DIR / filename

            with open(str(filepath), "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                writer.writerows(rows)

            report.file_path = str(filepath)
            report.format = "csv"
            db.session.commit()
            logger.info("generate_report: saved %s (%d rows)", filepath, len(rows))

        except OperationalError as exc:
            db.session.rollback()
            raise self.retry(exc=exc, countdown=30)
        except Exception:
            db.session.rollback()
            logger.exception("generate_report failed for report %s", report_id)
            raise


def _collect_data(report):
    """Dispatch to per-template collector. Returns (rows, headers)."""
    t = report.template_type
    start = report.date_range_start
    end = report.date_range_end
    cid = report.customer_id

    if t == "device_health":
        return _device_health(cid)
    elif t in ("patch_summary", "patch_compliance"):
        return _patch_compliance(cid, start, end)
    elif t == "alert_summary":
        return _alert_summary(cid, start, end)
    elif t == "software_inventory":
        return _software_inventory(cid)
    elif t == "ticket_summary":
        return _ticket_summary(cid, start, end)
    else:
        return [{"info": f"Unknown template type: {t}"}], ["info"]


def _device_health(customer_id):
    from models.device import Device, DeviceMetrics
    from sqlalchemy import func
    from extensions import db

    q = Device.query
    if customer_id:
        q = q.filter_by(customer_id=customer_id)
    devices = q.all()

    # Batch latest metrics
    dev_ids = [d.id for d in devices]
    subq = (
        db.select(func.max(DeviceMetrics.id).label("mid"))
        .where(DeviceMetrics.device_id.in_(dev_ids))
        .group_by(DeviceMetrics.device_id)
        .subquery()
    )
    metrics_list = db.session.execute(
        db.select(DeviceMetrics).join(subq, DeviceMetrics.id == subq.c.mid)
    ).scalars().all()
    m_map = {m.device_id: m for m in metrics_list}

    headers = ["hostname", "ip_address", "status", "os_name", "cpu_pct", "ram_pct", "disk_pct", "last_seen"]
    rows = []
    for d in devices:
        m = m_map.get(d.id)
        rows.append({
            "hostname": d.hostname,
            "ip_address": d.ip_address or "",
            "status": d.status or "",
            "os_name": d.os_name or "",
            "cpu_pct": round(m.cpu_pct, 1) if m and m.cpu_pct is not None else "",
            "ram_pct": round(m.ram_pct, 1) if m and m.ram_pct is not None else "",
            "disk_pct": round(m.disk_pct, 1) if m and m.disk_pct is not None else "",
            "last_seen": d.last_seen.isoformat() if d.last_seen else "",
        })
    return rows, headers


def _patch_compliance(customer_id, start, end):
    from models.patch import PatchRecord
    from models.device import Device

    q = PatchRecord.query
    if customer_id:
        dev_ids = [d.id for d in Device.query.filter_by(customer_id=customer_id).all()]
        if dev_ids:
            q = q.filter(PatchRecord.device_id.in_(dev_ids))
    if start:
        q = q.filter(PatchRecord.created_at >= start)
    if end:
        q = q.filter(PatchRecord.created_at <= end)

    headers = ["device_id", "patch_name", "kb_id", "patch_type", "source", "status", "created_at", "deployed_at"]
    rows = [
        {
            "device_id": p.device_id,
            "patch_name": p.patch_name,
            "kb_id": p.kb_id or "",
            "patch_type": p.patch_type or "",
            "source": p.source or "",
            "status": p.status,
            "created_at": p.created_at.isoformat() if p.created_at else "",
            "deployed_at": p.deployed_at.isoformat() if p.deployed_at else "",
        }
        for p in q.all()
    ]
    return rows, headers


def _alert_summary(customer_id, start, end):
    from models.alert import Alert
    from models.device import Device

    q = Alert.query
    if customer_id:
        dev_ids = [d.id for d in Device.query.filter_by(customer_id=customer_id).all()]
        if dev_ids:
            q = q.filter(Alert.device_id.in_(dev_ids))
    if start:
        q = q.filter(Alert.triggered_at >= start)
    if end:
        q = q.filter(Alert.triggered_at <= end)

    headers = ["device_id", "severity", "status", "message", "triggered_at", "resolved_at"]
    rows = [
        {
            "device_id": a.device_id,
            "severity": a.severity,
            "status": a.status,
            "message": a.message,
            "triggered_at": a.triggered_at.isoformat() if a.triggered_at else "",
            "resolved_at": a.resolved_at.isoformat() if a.resolved_at else "",
        }
        for a in q.all()
    ]
    return rows, headers


def _software_inventory(customer_id):
    from models.device import InstalledSoftware, Device

    q = InstalledSoftware.query
    if customer_id:
        dev_ids = [d.id for d in Device.query.filter_by(customer_id=customer_id).all()]
        if dev_ids:
            q = q.filter(InstalledSoftware.device_id.in_(dev_ids))

    headers = ["device_id", "name", "version", "publisher", "source", "install_date"]
    rows = [
        {
            "device_id": s.device_id,
            "name": s.name,
            "version": s.version or "",
            "publisher": s.publisher or "",
            "source": s.source or "",
            "install_date": s.install_date or "",
        }
        for s in q.order_by(InstalledSoftware.device_id, InstalledSoftware.name).all()
    ]
    return rows, headers


def _ticket_summary(customer_id, start, end):
    from models.ticket import Ticket

    q = Ticket.query
    if customer_id:
        q = q.filter_by(customer_id=customer_id)
    if start:
        q = q.filter(Ticket.created_at >= start)
    if end:
        q = q.filter(Ticket.created_at <= end)

    headers = ["title", "priority", "status", "source", "customer_id", "device_id", "created_at", "resolved_at"]
    rows = [
        {
            "title": t.title,
            "priority": t.priority,
            "status": t.status,
            "source": t.source or "",
            "customer_id": t.customer_id or "",
            "device_id": t.device_id or "",
            "created_at": t.created_at.isoformat() if t.created_at else "",
            "resolved_at": t.resolved_at.isoformat() if t.resolved_at else "",
        }
        for t in q.all()
    ]
    return rows, headers
