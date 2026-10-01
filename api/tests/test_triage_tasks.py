"""Tests for tasks/triage_tasks.py — the Celery scheduling shell around
services/ticket_triage_service.py. The real Anthropic API is always mocked."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import tasks._app_singleton as app_singleton
import tasks.triage_tasks as triage_tasks


def _make_customer(app):
    from extensions import db
    from models.customer import Customer
    c = Customer(name=f"TriageTaskCo-{uuid.uuid4().hex[:6]}", slug=f"tt-{uuid.uuid4().hex[:6]}", is_active=True)
    db.session.add(c)
    db.session.commit()
    return c


def _make_ticket(app, customer_id, **kwargs):
    from extensions import db
    from models.ticket import Ticket
    t = Ticket(
        title=kwargs.pop("title", "Triage task ticket"), customer_id=customer_id,
        status=kwargs.pop("status", "open"), triage_status=kwargs.pop("triage_status", "pending"),
        **kwargs,
    )
    db.session.add(t)
    db.session.commit()
    return t


def _make_category(app, code, **kwargs):
    from extensions import db
    from models.triage_category import TriageCategory
    c = TriageCategory(
        code=code, label=code.title(), description="test",
        is_active=kwargs.pop("is_active", True),
        auto_resolve_enabled=kwargs.pop("auto_resolve_enabled", True),
        shadow_mode=kwargs.pop("shadow_mode", False),
        confidence_threshold=kwargs.pop("confidence_threshold", 0.1),
        auto_close_days=kwargs.pop("auto_close_days", None),
    )
    db.session.add(c)
    db.session.commit()
    return c


def _cleanup(app, *, ticket_ids=(), category_ids=(), customer_ids=()):
    from extensions import db
    from models.ticket import Ticket, TicketComment
    from models.triage_category import TriageCategory
    from models.customer import Customer
    from models.audit import AuditLog
    for tid in ticket_ids:
        TicketComment.query.filter_by(ticket_id=tid).delete()
        AuditLog.query.filter_by(resource_type="ticket", resource_id=tid).delete()
        Ticket.query.filter_by(id=tid).delete()
    for cid in category_ids:
        TriageCategory.query.filter_by(id=cid).delete()
    for cust_id in customer_ids:
        Customer.query.filter_by(id=cust_id).delete()
    db.session.commit()


def _fake_anthropic_client(tool_input: dict):
    usage = MagicMock(input_tokens=42, output_tokens=17)
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.input = tool_input
    resp = MagicMock(content=[tool_block], usage=usage)
    client = MagicMock()
    client.messages.create.return_value = resp
    return client


class TestTriageTicket:
    def test_auto_resolves_whitelisted_high_confidence_ticket(self, app):
        app_singleton._app = app
        cust = _make_customer(app)
        cat = _make_category(app, f"autocat_{uuid.uuid4().hex[:6]}")
        ticket = _make_ticket(app, cust.id)
        try:
            fake_client = _fake_anthropic_client({
                "category": cat.code, "confidence": 0.95, "is_auto_resolvable": True,
                "draft_reply": "Please restart your device and the issue should clear.",
                "reasoning": "Common restart fix.",
            })
            with patch("services.ticket_triage_service.get_anthropic_client", return_value=fake_client):
                triage_tasks.triage_ticket(ticket.id)

            from extensions import db
            db.session.refresh(ticket)
            assert ticket.triage_status == "auto_resolved"
            assert ticket.status == "resolved"
            assert ticket.auto_resolved is True
            fake_client.messages.create.assert_called_once()
            _, kwargs = fake_client.messages.create.call_args
            assert kwargs["tool_choice"] == {"type": "tool", "name": "categorize_ticket"}
        finally:
            _cleanup(app, ticket_ids=[ticket.id], category_ids=[cat.id], customer_ids=[cust.id])

    def test_escalates_uncategorizable_ticket(self, app):
        app_singleton._app = app
        cust = _make_customer(app)
        ticket = _make_ticket(app, cust.id)
        try:
            fake_client = _fake_anthropic_client({
                "category": "other", "confidence": 0.3, "is_auto_resolvable": False,
                "draft_reply": "", "reasoning": "Unclear issue.",
            })
            with patch("services.ticket_triage_service.get_anthropic_client", return_value=fake_client):
                triage_tasks.triage_ticket(ticket.id)

            from extensions import db
            db.session.refresh(ticket)
            assert ticket.triage_status == "escalated"
            assert ticket.status == "open"
        finally:
            _cleanup(app, ticket_ids=[ticket.id], customer_ids=[cust.id])

    def test_idempotent_already_triaged_ticket_skips_second_call(self, app):
        app_singleton._app = app
        cust = _make_customer(app)
        ticket = _make_ticket(app, cust.id, triage_status="escalated")
        try:
            fake_client = _fake_anthropic_client({
                "category": "other", "confidence": 0.9, "is_auto_resolvable": False,
                "draft_reply": "", "reasoning": "n/a",
            })
            with patch("services.ticket_triage_service.get_anthropic_client", return_value=fake_client):
                triage_tasks.triage_ticket(ticket.id)
            fake_client.messages.create.assert_not_called()
        finally:
            _cleanup(app, ticket_ids=[ticket.id], customer_ids=[cust.id])

    def test_rate_limit_exceeded_escalates_without_calling_claude(self, app):
        app_singleton._app = app
        cust = _make_customer(app)
        ticket = _make_ticket(app, cust.id)
        try:
            fake_client = _fake_anthropic_client({
                "category": "other", "confidence": 0.9, "is_auto_resolvable": False,
                "draft_reply": "", "reasoning": "n/a",
            })
            with patch("services.ticket_triage_service.check_and_increment", return_value=False), \
                 patch("services.ticket_triage_service.get_anthropic_client", return_value=fake_client):
                triage_tasks.triage_ticket(ticket.id)

            from extensions import db
            db.session.refresh(ticket)
            assert ticket.triage_status == "skipped"
            fake_client.messages.create.assert_not_called()
        finally:
            _cleanup(app, ticket_ids=[ticket.id], customer_ids=[cust.id])

    def test_missing_ticket_is_a_clean_noop(self, app):
        app_singleton._app = app
        # Must not raise for a ticket id that doesn't exist (e.g. deleted after scheduling).
        triage_tasks.triage_ticket("nonexistent-ticket-id")

    def test_retries_on_anthropic_error(self, app):
        app_singleton._app = app
        cust = _make_customer(app)
        ticket = _make_ticket(app, cust.id)
        try:
            with patch("services.ticket_triage_service.get_anthropic_client",
                       side_effect=RuntimeError("API down")):
                try:
                    triage_tasks.triage_ticket(ticket.id)
                    assert False, "expected a retry-triggered exception"
                except Exception as exc:
                    assert exc is not None
        finally:
            _cleanup(app, ticket_ids=[ticket.id], customer_ids=[cust.id])


class TestAutoCloseResolvedTickets:
    def test_closes_ai_resolved_ticket_past_grace_period(self, app):
        app_singleton._app = app
        cust = _make_customer(app)
        old_resolved = datetime.now(timezone.utc) - timedelta(days=10)
        ticket = _make_ticket(app, cust.id, status="resolved")
        ticket.auto_resolved = True
        ticket.resolved_at = old_resolved
        from extensions import db
        db.session.commit()
        try:
            triage_tasks.auto_close_resolved_tickets()
            db.session.refresh(ticket)
            assert ticket.status == "closed"
        finally:
            _cleanup(app, ticket_ids=[ticket.id], customer_ids=[cust.id])

    def test_leaves_recently_resolved_ticket_open(self, app):
        app_singleton._app = app
        cust = _make_customer(app)
        recent_resolved = datetime.now(timezone.utc) - timedelta(days=1)
        ticket = _make_ticket(app, cust.id, status="resolved")
        ticket.auto_resolved = True
        ticket.resolved_at = recent_resolved
        from extensions import db
        db.session.commit()
        try:
            triage_tasks.auto_close_resolved_tickets()
            db.session.refresh(ticket)
            assert ticket.status == "resolved"
        finally:
            _cleanup(app, ticket_ids=[ticket.id], customer_ids=[cust.id])

    def test_never_touches_human_resolved_ticket(self, app):
        app_singleton._app = app
        cust = _make_customer(app)
        old_resolved = datetime.now(timezone.utc) - timedelta(days=30)
        ticket = _make_ticket(app, cust.id, status="resolved")
        ticket.auto_resolved = False  # resolved by a human, not AI
        ticket.resolved_at = old_resolved
        from extensions import db
        db.session.commit()
        try:
            triage_tasks.auto_close_resolved_tickets()
            db.session.refresh(ticket)
            assert ticket.status == "resolved"
        finally:
            _cleanup(app, ticket_ids=[ticket.id], customer_ids=[cust.id])

    def test_respects_per_category_auto_close_override(self, app):
        app_singleton._app = app
        cust = _make_customer(app)
        cat = _make_category(app, f"shortclose_{uuid.uuid4().hex[:6]}", auto_close_days=1)
        resolved_2_days_ago = datetime.now(timezone.utc) - timedelta(days=2)
        ticket = _make_ticket(app, cust.id, status="resolved", category=cat.code)
        ticket.auto_resolved = True
        ticket.resolved_at = resolved_2_days_ago
        from extensions import db
        db.session.commit()
        try:
            # Global default is 7 days, but this category overrides to 1 — should close.
            triage_tasks.auto_close_resolved_tickets()
            db.session.refresh(ticket)
            assert ticket.status == "closed"
        finally:
            _cleanup(app, ticket_ids=[ticket.id], category_ids=[cat.id], customer_ids=[cust.id])
