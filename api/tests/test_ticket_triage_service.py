"""Tests for services/ticket_triage_service.py::apply_triage_decision — the
server-side gate that decides escalate/stage/auto-resolve. Never calls the real
Anthropic API; these tests feed decision inputs directly."""
import uuid
import pytest
from conftest import create_user, delete_user


def _make_customer(app):
    from extensions import db
    from models.customer import Customer
    c = Customer(name=f"TriageCo-{uuid.uuid4().hex[:6]}", slug=f"tr-{uuid.uuid4().hex[:6]}", is_active=True)
    db.session.add(c)
    db.session.commit()
    return c


def _make_ticket(app, customer_id, **kwargs):
    from extensions import db
    from models.ticket import Ticket
    t = Ticket(
        title=kwargs.pop("title", "Test ticket"),
        customer_id=customer_id,
        status=kwargs.pop("status", "open"),
        triage_status="pending",
        **kwargs,
    )
    db.session.add(t)
    db.session.commit()
    return t


def _make_category(app, code, *, auto_resolve_enabled=False, shadow_mode=True, confidence_threshold=0.85,
                   is_active=True):
    from extensions import db
    from models.triage_category import TriageCategory
    c = TriageCategory(
        code=code, label=code.title(), description="test category",
        is_active=is_active, auto_resolve_enabled=auto_resolve_enabled,
        shadow_mode=shadow_mode, confidence_threshold=confidence_threshold,
    )
    db.session.add(c)
    db.session.commit()
    return c


def _cleanup(app, *, ticket_ids=None, category_ids=None, customer_ids=None):
    from extensions import db
    from models.ticket import Ticket, TicketComment
    from models.triage_category import TriageCategory
    from models.customer import Customer
    from models.audit import AuditLog
    for tid in (ticket_ids or []):
        TicketComment.query.filter_by(ticket_id=tid).delete()
        AuditLog.query.filter_by(resource_type="ticket", resource_id=tid).delete()
        Ticket.query.filter_by(id=tid).delete()
    for cid in (category_ids or []):
        TriageCategory.query.filter_by(id=cid).delete()
    for cust_id in (customer_ids or []):
        Customer.query.filter_by(id=cust_id).delete()
    db.session.commit()


class TestApplyTriageDecision:
    def test_other_category_always_escalates(self, app):
        from services.ticket_triage_service import apply_triage_decision
        with app.app_context():
            cust = _make_customer(app)
            ticket = _make_ticket(app, cust.id)
            try:
                result = apply_triage_decision(
                    ticket, category="other", confidence=0.99, is_auto_resolvable=True,
                    draft_reply="Here is how to fix it.", reasoning="n/a", model="test-model",
                )
                assert result == "escalated"
                assert ticket.triage_status == "escalated"
                assert ticket.category == "other"
            finally:
                _cleanup(app, ticket_ids=[ticket.id], customer_ids=[cust.id])

    def test_not_whitelisted_category_escalates(self, app):
        from services.ticket_triage_service import apply_triage_decision
        with app.app_context():
            cust = _make_customer(app)
            ticket = _make_ticket(app, cust.id)
            cat = _make_category(app, f"nowhitelist_{uuid.uuid4().hex[:6]}", auto_resolve_enabled=False)
            try:
                result = apply_triage_decision(
                    ticket, category=cat.code, confidence=0.99, is_auto_resolvable=True,
                    draft_reply="Fix.", reasoning="n/a", model="test-model",
                )
                assert result == "escalated"
                assert ticket.triage_status == "escalated"
            finally:
                _cleanup(app, ticket_ids=[ticket.id], category_ids=[cat.id], customer_ids=[cust.id])

    def test_below_confidence_threshold_escalates_even_if_whitelisted(self, app):
        from services.ticket_triage_service import apply_triage_decision
        with app.app_context():
            cust = _make_customer(app)
            ticket = _make_ticket(app, cust.id)
            cat = _make_category(app, f"lowconf_{uuid.uuid4().hex[:6]}",
                                 auto_resolve_enabled=True, shadow_mode=False, confidence_threshold=0.9)
            try:
                result = apply_triage_decision(
                    ticket, category=cat.code, confidence=0.5, is_auto_resolvable=True,
                    draft_reply="Fix.", reasoning="n/a", model="test-model",
                )
                assert result == "escalated"
            finally:
                _cleanup(app, ticket_ids=[ticket.id], category_ids=[cat.id], customer_ids=[cust.id])

    def test_whitelisted_shadow_mode_stages_for_approval(self, app):
        from services.ticket_triage_service import apply_triage_decision
        with app.app_context():
            cust = _make_customer(app)
            ticket = _make_ticket(app, cust.id)
            cat = _make_category(app, f"shadow_{uuid.uuid4().hex[:6]}",
                                 auto_resolve_enabled=True, shadow_mode=True, confidence_threshold=0.5)
            try:
                result = apply_triage_decision(
                    ticket, category=cat.code, confidence=0.9, is_auto_resolvable=True,
                    draft_reply="Please try restarting the device.", reasoning="n/a", model="test-model",
                )
                assert result == "staged"
                assert ticket.triage_status == "staged"
                assert ticket.status == "open"  # unchanged — awaiting human approval
                assert ticket.ai_suggested_reply == "Please try restarting the device."
            finally:
                _cleanup(app, ticket_ids=[ticket.id], category_ids=[cat.id], customer_ids=[cust.id])

    def test_whitelisted_shadow_off_auto_resolves(self, app):
        from services.ticket_triage_service import apply_triage_decision
        with app.app_context():
            cust = _make_customer(app)
            ticket = _make_ticket(app, cust.id)
            cat = _make_category(app, f"auto_{uuid.uuid4().hex[:6]}",
                                 auto_resolve_enabled=True, shadow_mode=False, confidence_threshold=0.5)
            try:
                result = apply_triage_decision(
                    ticket, category=cat.code, confidence=0.95, is_auto_resolvable=True,
                    draft_reply="Please try restarting the device.", reasoning="n/a", model="test-model",
                )
                assert result == "auto_resolved"
                assert ticket.triage_status == "auto_resolved"
                assert ticket.status == "resolved"
                assert ticket.auto_resolved is True
                assert ticket.resolved_at is not None
            finally:
                _cleanup(app, ticket_ids=[ticket.id], category_ids=[cat.id], customer_ids=[cust.id])

    def test_danger_pattern_in_reply_forces_escalation_even_when_fully_whitelisted(self, app):
        """The key safety-net test: a model that says is_auto_resolvable=True on a
        fully-whitelisted, high-confidence category must still be overridden when
        its own drafted reply contains a destructive-looking pattern."""
        from services.ticket_triage_service import apply_triage_decision
        with app.app_context():
            cust = _make_customer(app)
            ticket = _make_ticket(app, cust.id)
            cat = _make_category(app, f"danger_{uuid.uuid4().hex[:6]}",
                                 auto_resolve_enabled=True, shadow_mode=False, confidence_threshold=0.1)
            try:
                result = apply_triage_decision(
                    ticket, category=cat.code, confidence=0.99, is_auto_resolvable=True,
                    draft_reply="Just run: rm -rf /data to clear it out.",
                    reasoning="n/a", model="test-model",
                )
                assert result == "escalated"
                assert ticket.triage_status == "escalated"
                assert ticket.status == "open"
            finally:
                _cleanup(app, ticket_ids=[ticket.id], category_ids=[cat.id], customer_ids=[cust.id])

    def test_inactive_category_escalates(self, app):
        from services.ticket_triage_service import apply_triage_decision
        with app.app_context():
            cust = _make_customer(app)
            ticket = _make_ticket(app, cust.id)
            cat = _make_category(app, f"inactive_{uuid.uuid4().hex[:6]}",
                                 auto_resolve_enabled=True, shadow_mode=False,
                                 confidence_threshold=0.1, is_active=False)
            try:
                result = apply_triage_decision(
                    ticket, category=cat.code, confidence=0.99, is_auto_resolvable=True,
                    draft_reply="Fix.", reasoning="n/a", model="test-model",
                )
                assert result == "escalated"
            finally:
                _cleanup(app, ticket_ids=[ticket.id], category_ids=[cat.id], customer_ids=[cust.id])


class TestDangerScan:
    def test_detects_destructive_pattern(self):
        from services.ticket_triage_service import danger_scan
        assert danger_scan("Please run rm -rf /tmp/cache") is True

    def test_clean_text_passes(self):
        from services.ticket_triage_service import danger_scan
        assert danger_scan("Please restart your device and try again.") is False

    def test_empty_text_passes(self):
        from services.ticket_triage_service import danger_scan
        assert danger_scan("") is False
