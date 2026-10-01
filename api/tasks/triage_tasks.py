"""AI ticket triage tasks — on-demand categorization + the auto-close sweep for
tickets the AI resolved on its own. See services/ticket_triage_service.py for the
actual categorization/decision logic; this module is just the Celery scheduling
shell, mirroring tasks/ticket_tasks.py::check_sla_breaches."""
import os
import logging
from datetime import datetime, timezone, timedelta
from tasks.celery_app import celery

logger = logging.getLogger(__name__)

from tasks._app_singleton import get_app as _get_app


@celery.task(name="tasks.triage_tasks.triage_ticket", bind=True, max_retries=2)
def triage_ticket(self, ticket_id: str):
    from extensions import db
    from models.ticket import Ticket
    from services.ticket_triage_service import run_triage

    with _get_app().app_context():
        try:
            ticket = db.session.get(Ticket, ticket_id)
            if not ticket:
                return
            # Idempotency guard — a ticket already processed (or mid-flight) is
            # skipped rather than re-triaged, protecting against duplicate
            # .delay() calls or Celery redelivery under task_acks_late=True.
            if ticket.triage_status not in (None, "pending"):
                logger.info("Ticket %s already triaged (status=%s) — skipping", ticket_id, ticket.triage_status)
                return
            run_triage(ticket_id)
            logger.info("Triaged ticket %s", ticket_id)
        except Exception as exc:
            db.session.rollback()
            logger.exception("triage_ticket failed for %s", ticket_id)
            raise self.retry(exc=exc, countdown=60)


@celery.task(name="tasks.triage_tasks.auto_close_resolved_tickets", bind=True, max_retries=2)
def auto_close_resolved_tickets(self):
    """Closes tickets the AI auto-resolved once their per-category (or global)
    grace period has passed with no customer reply (a reply reopens the ticket
    via poll_support_inbox, clearing auto_resolved, before this would ever run)."""
    from extensions import db
    from models.ticket import Ticket
    from models.triage_category import TriageCategory

    default_days = int(os.getenv("AI_TRIAGE_AUTO_CLOSE_DAYS", "7"))

    with _get_app().app_context():
        try:
            now = datetime.now(timezone.utc)
            candidates = Ticket.query.filter(
                Ticket.status == "resolved",
                Ticket.auto_resolved == True,  # noqa: E712
                Ticket.resolved_at != None,  # noqa: E711
            ).all()

            days_by_category = {
                c.code: c.auto_close_days for c in TriageCategory.query.all() if c.auto_close_days
            }

            closed = 0
            for ticket in candidates:
                days = days_by_category.get(ticket.category, default_days)
                resolved_at = ticket.resolved_at
                if resolved_at.tzinfo is None:
                    # SQLite (tests) doesn't persist tzinfo on DateTime(timezone=True)
                    # columns — the values we wrote were always UTC, so treat a naive
                    # read-back as UTC rather than letting it raise on comparison.
                    resolved_at = resolved_at.replace(tzinfo=timezone.utc)
                if resolved_at < now - timedelta(days=days):
                    ticket.status = "closed"
                    ticket.updated_at = now
                    closed += 1

            if closed:
                db.session.commit()
                logger.info("Auto-close sweep: closed %d AI-resolved ticket(s)", closed)
        except Exception as exc:
            db.session.rollback()
            logger.exception("auto_close_resolved_tickets failed")
            raise self.retry(exc=exc, countdown=60)
