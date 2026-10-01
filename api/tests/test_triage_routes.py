"""Tests for routes/ticket_triage.py — approve/reject on staged AI suggestions,
and admin CRUD on the triage_categories whitelist."""
import uuid
from conftest import create_user, delete_user, login, auth_headers


def _make_customer(app):
    from extensions import db
    from models.customer import Customer
    c = Customer(name=f"TriageRouteCo-{uuid.uuid4().hex[:6]}", slug=f"trc-{uuid.uuid4().hex[:6]}", is_active=True)
    db.session.add(c)
    db.session.commit()
    return c


def _make_staged_ticket(app, customer_id, *, suggested_reply="Try restarting your device."):
    from extensions import db
    from models.ticket import Ticket
    t = Ticket(
        title="Staged ticket", customer_id=customer_id, status="open",
        triage_status="staged", category="account_access",
        ai_suggested_category="account_access", ai_confidence=0.9,
        ai_suggested_reply=suggested_reply,
    )
    db.session.add(t)
    db.session.commit()
    return t


def _make_category(app, code="test_cat"):
    from extensions import db
    from models.triage_category import TriageCategory
    c = TriageCategory(code=code, label="Test Cat", description="d",
                       is_active=True, auto_resolve_enabled=False, shadow_mode=True,
                       confidence_threshold=0.85)
    db.session.add(c)
    db.session.commit()
    return c


def _cleanup(app, *, ticket_ids=(), category_ids=(), customer_id=None, user_id=None):
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
    if customer_id:
        Customer.query.filter_by(id=customer_id).delete()
    db.session.commit()
    if user_id:
        delete_user(app, user_id)


class TestApproveTriage:
    def test_requires_auth(self, client):
        r = client.post("/api/tickets/nonexistent/triage/approve")
        assert r.status_code == 401

    def test_client_role_forbidden(self, app, client):
        uid, email, pw = create_user(app, role="client")
        cust = _make_customer(app)
        ticket = _make_staged_ticket(app, cust.id)
        try:
            token = login(client, email, pw).get_json()["access_token"]
            r = client.post(f"/api/tickets/{ticket.id}/triage/approve", headers=auth_headers(token))
            assert r.status_code == 403
        finally:
            _cleanup(app, ticket_ids=[ticket.id], customer_id=cust.id, user_id=uid)

    def test_technician_approves_staged_ticket(self, app, client):
        uid, email, pw = create_user(app, role="technician")
        cust = _make_customer(app)
        ticket = _make_staged_ticket(app, cust.id)
        try:
            token = login(client, email, pw).get_json()["access_token"]
            r = client.post(f"/api/tickets/{ticket.id}/triage/approve", headers=auth_headers(token))
            assert r.status_code == 200, r.get_json()
            body = r.get_json()
            assert body["status"] == "resolved"
            assert body["auto_resolved"] is True
            assert body["triage_status"] == "auto_resolved"
        finally:
            _cleanup(app, ticket_ids=[ticket.id], customer_id=cust.id, user_id=uid)

    def test_approve_with_reply_override_uses_override_text(self, app, client):
        uid, email, pw = create_user(app, role="admin")
        cust = _make_customer(app)
        ticket = _make_staged_ticket(app, cust.id)
        try:
            token = login(client, email, pw).get_json()["access_token"]
            r = client.post(
                f"/api/tickets/{ticket.id}/triage/approve",
                json={"reply_override": "Edited human reply."},
                headers=auth_headers(token), content_type="application/json",
            )
            assert r.status_code == 200
            assert r.get_json()["ai_suggested_reply"] == "Edited human reply."
        finally:
            _cleanup(app, ticket_ids=[ticket.id], customer_id=cust.id, user_id=uid)

    def test_approve_rejects_dangerous_override(self, app, client):
        uid, email, pw = create_user(app, role="admin")
        cust = _make_customer(app)
        ticket = _make_staged_ticket(app, cust.id)
        try:
            token = login(client, email, pw).get_json()["access_token"]
            r = client.post(
                f"/api/tickets/{ticket.id}/triage/approve",
                json={"reply_override": "Just run rm -rf / to fix it."},
                headers=auth_headers(token), content_type="application/json",
            )
            assert r.status_code == 400
        finally:
            _cleanup(app, ticket_ids=[ticket.id], customer_id=cust.id, user_id=uid)

    def test_approve_fails_when_not_staged(self, app, client):
        uid, email, pw = create_user(app, role="admin")
        cust = _make_customer(app)
        from extensions import db
        from models.ticket import Ticket
        ticket = Ticket(title="Not staged", customer_id=cust.id, status="open", triage_status="escalated")
        db.session.add(ticket)
        db.session.commit()
        try:
            token = login(client, email, pw).get_json()["access_token"]
            r = client.post(f"/api/tickets/{ticket.id}/triage/approve", headers=auth_headers(token))
            assert r.status_code == 409
        finally:
            _cleanup(app, ticket_ids=[ticket.id], customer_id=cust.id, user_id=uid)


class TestRejectTriage:
    def test_technician_rejects_staged_ticket(self, app, client):
        uid, email, pw = create_user(app, role="technician")
        cust = _make_customer(app)
        ticket = _make_staged_ticket(app, cust.id)
        try:
            token = login(client, email, pw).get_json()["access_token"]
            r = client.post(f"/api/tickets/{ticket.id}/triage/reject", headers=auth_headers(token))
            assert r.status_code == 200
            body = r.get_json()
            assert body["triage_status"] == "escalated"
            assert body["status"] == "open"  # untouched — human takes over normally
        finally:
            _cleanup(app, ticket_ids=[ticket.id], customer_id=cust.id, user_id=uid)

    def test_reject_with_assignee(self, app, client):
        uid, email, pw = create_user(app, role="admin")
        assignee_id, _, _ = create_user(app, role="technician")
        cust = _make_customer(app)
        ticket = _make_staged_ticket(app, cust.id)
        try:
            token = login(client, email, pw).get_json()["access_token"]
            r = client.post(
                f"/api/tickets/{ticket.id}/triage/reject",
                json={"assignee_id": assignee_id},
                headers=auth_headers(token), content_type="application/json",
            )
            assert r.status_code == 200
            assert r.get_json()["assignee_id"] == assignee_id
        finally:
            _cleanup(app, ticket_ids=[ticket.id], customer_id=cust.id, user_id=uid)
            delete_user(app, assignee_id)


class TestTriageCategories:
    def test_list_requires_auth(self, client):
        r = client.get("/api/triage/categories/")
        assert r.status_code == 401

    def test_any_authenticated_role_can_list(self, app, client):
        uid, email, pw = create_user(app, role="viewer")
        try:
            token = login(client, email, pw).get_json()["access_token"]
            r = client.get("/api/triage/categories/", headers=auth_headers(token))
            assert r.status_code == 200
            assert isinstance(r.get_json(), list)
        finally:
            delete_user(app, uid)

    def test_technician_cannot_update_category(self, app, client):
        uid, email, pw = create_user(app, role="technician")
        cat = _make_category(app, f"nocat_{uuid.uuid4().hex[:6]}")
        try:
            token = login(client, email, pw).get_json()["access_token"]
            r = client.put(f"/api/triage/categories/{cat.id}", json={"auto_resolve_enabled": True},
                           headers=auth_headers(token), content_type="application/json")
            assert r.status_code == 403
        finally:
            _cleanup(app, category_ids=[cat.id], user_id=uid)

    def test_admin_can_flip_whitelist_and_shadow_mode(self, app, client):
        uid, email, pw = create_user(app, role="admin")
        cat = _make_category(app, f"flip_{uuid.uuid4().hex[:6]}")
        try:
            token = login(client, email, pw).get_json()["access_token"]
            r = client.put(
                f"/api/triage/categories/{cat.id}",
                json={"auto_resolve_enabled": True, "shadow_mode": False, "confidence_threshold": 0.9},
                headers=auth_headers(token), content_type="application/json",
            )
            assert r.status_code == 200, r.get_json()
            body = r.get_json()
            assert body["auto_resolve_enabled"] is True
            assert body["shadow_mode"] is False
            assert body["confidence_threshold"] == 0.9
        finally:
            _cleanup(app, category_ids=[cat.id], user_id=uid)

    def test_invalid_confidence_threshold_rejected(self, app, client):
        uid, email, pw = create_user(app, role="admin")
        cat = _make_category(app, f"badconf_{uuid.uuid4().hex[:6]}")
        try:
            token = login(client, email, pw).get_json()["access_token"]
            r = client.put(f"/api/triage/categories/{cat.id}", json={"confidence_threshold": 1.5},
                           headers=auth_headers(token), content_type="application/json")
            assert r.status_code == 400
        finally:
            _cleanup(app, category_ids=[cat.id], user_id=uid)

    def test_invalid_auto_close_days_rejected(self, app, client):
        uid, email, pw = create_user(app, role="admin")
        cat = _make_category(app, f"baddays_{uuid.uuid4().hex[:6]}")
        try:
            token = login(client, email, pw).get_json()["access_token"]
            r = client.put(f"/api/triage/categories/{cat.id}", json={"auto_close_days": 0},
                           headers=auth_headers(token), content_type="application/json")
            assert r.status_code == 400
        finally:
            _cleanup(app, category_ids=[cat.id], user_id=uid)
