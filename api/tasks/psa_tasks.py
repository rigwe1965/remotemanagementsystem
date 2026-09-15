"""PSA sync Celery tasks — ConnectWise Manage + Autotask."""
import logging
from datetime import datetime, timezone, timedelta

from tasks.celery_app import celery

logger = logging.getLogger(__name__)

_app = None


def _get_app():
    global _app
    if _app is None:
        from app import create_app
        _app = create_app()
    return _app


@celery.task(name="tasks.psa_tasks.sync_all_psa_integrations", bind=True, max_retries=1)
def sync_all_psa_integrations(self):
    """Fan-out: dispatch one sync task per active PSA integration."""
    app = _get_app()
    with app.app_context():
        from models.psa_integration import PsaIntegration
        active = PsaIntegration.query.filter_by(is_active=True).all()
        for integration in active:
            sync_psa_integration.delay(integration.id)
        logger.info("PSA sync: dispatched %d integration(s)", len(active))


@celery.task(name="tasks.psa_tasks.sync_psa_integration", bind=True, max_retries=2)
def sync_psa_integration(self, psa_integration_id: str):
    """Full sync for one integration: companies → tickets push → tickets pull → configs."""
    app = _get_app()
    with app.app_context():
        from extensions import db
        from models.psa_integration import PsaIntegration

        integration = db.session.get(PsaIntegration, psa_integration_id)
        if not integration or not integration.is_active:
            return

        try:
            client = integration.get_client()

            if integration.sync_companies:
                _sync_companies(app, integration, client)

            if integration.sync_tickets:
                _push_unmapped_tickets(app, integration, client)
                _pull_psa_tickets(app, integration, client)

            if integration.sync_configs:
                _sync_configs(app, integration, client)

            integration.last_sync_at = datetime.now(timezone.utc)
            integration.sync_error = None
            db.session.commit()
            logger.info("PSA sync complete: %s (%s)", integration.name, integration.type)

        except Exception as exc:
            logger.error("PSA sync failed for %s: %s", psa_integration_id, exc)
            integration.sync_error = str(exc)[:500]
            db.session.commit()
            raise self.retry(exc=exc, countdown=120)


def _sync_companies(app, integration, client):
    """Auto-match PSA companies to local customers by name (case-insensitive)."""
    from extensions import db
    from models.customer import Customer
    from models.psa_integration import PsaCompanyMap

    psa_companies = client.get_companies()
    if not psa_companies:
        return

    customers = Customer.query.filter_by(is_active=True).all()
    psa_by_name = {c["name"].lower(): c for c in psa_companies}

    for customer in customers:
        psa_match = psa_by_name.get(customer.name.lower())
        if not psa_match:
            continue
        existing = PsaCompanyMap.query.filter_by(
            psa_integration_id=integration.id,
            customer_id=customer.id,
        ).first()
        if existing:
            existing.psa_company_id = psa_match["id"]
            existing.psa_company_name = psa_match["name"]
            existing.synced_at = datetime.now(timezone.utc)
        else:
            db.session.add(PsaCompanyMap(
                psa_integration_id=integration.id,
                customer_id=customer.id,
                psa_company_id=psa_match["id"],
                psa_company_name=psa_match["name"],
            ))

    db.session.commit()
    logger.debug("PSA company sync done for %s", integration.name)


def _push_unmapped_tickets(app, integration, client):
    """Push local open/in_progress tickets that have no PSA map entry yet."""
    from extensions import db
    from models.ticket import Ticket
    from models.psa_integration import PsaTicketMap, PsaCompanyMap

    mapped_ids = {
        m.ticket_id
        for m in PsaTicketMap.query.filter_by(psa_integration_id=integration.id).all()
    }
    tickets = Ticket.query.filter(
        Ticket.status.in_(["open", "in_progress"]),
        ~Ticket.id.in_(mapped_ids) if mapped_ids else True,
    ).all()

    pushed = 0
    for ticket in tickets:
        cmap = PsaCompanyMap.query.filter_by(
            psa_integration_id=integration.id,
            customer_id=ticket.customer_id,
        ).first()
        if not cmap:
            continue

        psa_id = client.push_ticket(ticket, cmap.psa_company_id)
        if psa_id:
            db.session.add(PsaTicketMap(
                psa_integration_id=integration.id,
                ticket_id=ticket.id,
                psa_ticket_id=psa_id,
            ))
            pushed += 1

    if pushed:
        db.session.commit()
    logger.debug("PSA pushed %d new ticket(s) for %s", pushed, integration.name)


def _pull_psa_tickets(app, integration, client):
    """Pull PSA tickets modified in last 2h and update local mapped tickets."""
    from extensions import db
    from models.ticket import Ticket
    from models.psa_integration import PsaTicketMap

    since = datetime.now(timezone.utc) - timedelta(hours=2)
    psa_tickets = client.pull_tickets(since)
    if not psa_tickets:
        return

    psa_id_to_map = {
        m.psa_ticket_id: m
        for m in PsaTicketMap.query.filter_by(psa_integration_id=integration.id).all()
    }

    updated = 0
    for pt in psa_tickets:
        tmap = psa_id_to_map.get(pt["psa_ticket_id"])
        if not tmap:
            continue
        local = db.session.get(Ticket, tmap.ticket_id)
        if not local:
            continue
        changed = False
        if pt.get("status") and pt["status"] != local.status:
            local.status = pt["status"]
            if pt["status"] in ("resolved", "closed") and not local.resolved_at:
                local.resolved_at = datetime.now(timezone.utc)
            changed = True
        if pt.get("priority") and pt["priority"] != local.priority:
            local.priority = pt["priority"]
            changed = True
        if changed:
            local.updated_at = datetime.now(timezone.utc)
            tmap.last_synced_at = datetime.now(timezone.utc)
            updated += 1

    if updated:
        db.session.commit()
    logger.debug("PSA pulled %d ticket update(s) for %s", updated, integration.name)


def _sync_configs(app, integration, client):
    """Push online devices as configuration items in PSA (for mapped companies only)."""
    from extensions import db
    from models.device import Device
    from models.psa_integration import PsaCompanyMap

    company_maps = {
        m.customer_id: m
        for m in PsaCompanyMap.query.filter_by(psa_integration_id=integration.id).all()
    }
    if not company_maps:
        return

    devices = Device.query.filter(
        Device.customer_id.in_(list(company_maps.keys())),
        Device.is_agentless == False,  # noqa: E712
    ).all()

    pushed = 0
    for device in devices:
        cmap = company_maps.get(device.customer_id)
        if not cmap:
            continue
        result = client.push_config_item(device, cmap.psa_company_id)
        if result:
            pushed += 1

    logger.debug("PSA pushed %d config item(s) for %s", pushed, integration.name)
