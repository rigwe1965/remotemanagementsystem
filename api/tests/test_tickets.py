"""Tests for ticket CRUD, SLA due_date calculation, comments, and role-gating."""
import uuid
from unittest.mock import patch
import pytest
from conftest import create_user, delete_user, login, auth_headers


def _make_customer(app):
    from extensions import db
    from models.customer import Customer
    c = Customer(name=f"TicketCo-{uuid.uuid4().hex[:6]}", slug=f"tc-{uuid.uuid4().hex[:6]}", is_active=True)
    db.session.add(c)
    db.session.commit()
    return c


def _del_customer(app, cid):
    from extensions import db
    from models.customer import Customer
    from models.ticket import Ticket, TicketComment
    ticket_ids = [t.id for t in Ticket.query.filter_by(customer_id=cid).all()]
    if ticket_ids:
        TicketComment.query.filter(TicketComment.ticket_id.in_(ticket_ids)).delete(synchronize_session=False)
    Ticket.query.filter_by(customer_id=cid).delete()
    Customer.query.filter_by(id=cid).delete()
    db.session.commit()


class TestTicketCRUD:
    def test_list_requires_auth(self, client):
        r = client.get("/api/tickets/")
        assert r.status_code == 401

    def test_create_and_list(self, app, client):
        uid, email, pw = create_user(app, role="admin")
        cust = _make_customer(app)
        try:
            tok = login(client, email, pw).get_json()["access_token"]
            r = client.post(
                "/api/tickets/",
                json={"title": "Server Down", "customer_id": cust.id, "priority": "high"},
                headers=auth_headers(tok),
                content_type="application/json",
            )
            assert r.status_code == 201, r.get_json()
            body = r.get_json()
            assert body["title"] == "Server Down"
            assert body["status"] == "open"
            assert body["due_date"] is not None  # SLA applied

            r2 = client.get("/api/tickets/", headers=auth_headers(tok))
            assert r2.status_code == 200
            assert r2.get_json()["total"] >= 1
        finally:
            delete_user(app, uid)
            _del_customer(app, cust.id)

    def test_create_missing_title(self, app, client):
        uid, email, pw = create_user(app, role="admin")
        cust = _make_customer(app)
        try:
            tok = login(client, email, pw).get_json()["access_token"]
            r = client.post(
                "/api/tickets/",
                json={"customer_id": cust.id},
                headers=auth_headers(tok),
                content_type="application/json",
            )
            assert r.status_code == 400
        finally:
            delete_user(app, uid)
            _del_customer(app, cust.id)

    def test_create_missing_customer(self, app, client):
        uid, email, pw = create_user(app, role="admin")
        try:
            tok = login(client, email, pw).get_json()["access_token"]
            r = client.post(
                "/api/tickets/",
                json={"title": "No customer"},
                headers=auth_headers(tok),
                content_type="application/json",
            )
            assert r.status_code == 400
        finally:
            delete_user(app, uid)

    def test_viewer_cannot_create(self, app, client):
        uid, email, pw = create_user(app, role="viewer")
        cust = _make_customer(app)
        try:
            tok = login(client, email, pw).get_json()["access_token"]
            r = client.post(
                "/api/tickets/",
                json={"title": "Test", "customer_id": cust.id},
                headers=auth_headers(tok),
                content_type="application/json",
            )
            assert r.status_code == 403
        finally:
            delete_user(app, uid)
            _del_customer(app, cust.id)

    def test_get_ticket(self, app, client):
        uid, email, pw = create_user(app, role="technician")
        cust = _make_customer(app)
        try:
            tok = login(client, email, pw).get_json()["access_token"]
            r = client.post(
                "/api/tickets/",
                json={"title": "Get me", "customer_id": cust.id},
                headers=auth_headers(tok),
                content_type="application/json",
            )
            tid = r.get_json()["id"]
            r2 = client.get(f"/api/tickets/{tid}", headers=auth_headers(tok))
            assert r2.status_code == 200
            assert r2.get_json()["id"] == tid
        finally:
            delete_user(app, uid)
            _del_customer(app, cust.id)

    def test_update_status(self, app, client):
        uid, email, pw = create_user(app, role="technician")
        cust = _make_customer(app)
        try:
            tok = login(client, email, pw).get_json()["access_token"]
            r = client.post(
                "/api/tickets/",
                json={"title": "Resolve me", "customer_id": cust.id},
                headers=auth_headers(tok),
                content_type="application/json",
            )
            tid = r.get_json()["id"]
            r2 = client.put(
                f"/api/tickets/{tid}",
                json={"status": "resolved", "status_comment": "Issue fixed."},
                headers=auth_headers(tok),
                content_type="application/json",
            )
            assert r2.status_code == 200, r2.get_json()
            assert r2.get_json()["status"] == "resolved"
            assert r2.get_json()["resolved_at"] is not None
        finally:
            delete_user(app, uid)
            _del_customer(app, cust.id)


def _parse_due(due_str: str):
    """Parse ISO due_date from API; always return a UTC-aware datetime."""
    from datetime import datetime, timezone
    dt = datetime.fromisoformat(due_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class TestTicketSLA:
    def test_critical_ticket_due_date_within_4_hours(self, app, client):
        from datetime import datetime, timezone
        uid, email, pw = create_user(app, role="admin")
        cust = _make_customer(app)
        try:
            tok = login(client, email, pw).get_json()["access_token"]
            r = client.post(
                "/api/tickets/",
                json={"title": "P1", "customer_id": cust.id, "priority": "critical"},
                headers=auth_headers(tok),
                content_type="application/json",
            )
            assert r.status_code == 201
            due = r.get_json()["due_date"]
            assert due is not None
            delta_hours = (_parse_due(due) - datetime.now(timezone.utc)).total_seconds() / 3600
            assert 3.5 <= delta_hours <= 4.5, f"Critical SLA should be ~4h, got {delta_hours:.1f}h"
        finally:
            delete_user(app, uid)
            _del_customer(app, cust.id)

    def test_low_ticket_due_date_within_72_hours(self, app, client):
        from datetime import datetime, timezone
        uid, email, pw = create_user(app, role="admin")
        cust = _make_customer(app)
        try:
            tok = login(client, email, pw).get_json()["access_token"]
            r = client.post(
                "/api/tickets/",
                json={"title": "Low priority", "customer_id": cust.id, "priority": "low"},
                headers=auth_headers(tok),
                content_type="application/json",
            )
            due = r.get_json()["due_date"]
            delta_hours = (_parse_due(due) - datetime.now(timezone.utc)).total_seconds() / 3600
            assert 71 <= delta_hours <= 73, f"Low SLA should be ~72h, got {delta_hours:.1f}h"
        finally:
            delete_user(app, uid)
            _del_customer(app, cust.id)


class TestTicketTriageScheduling:
    """create_ticket_service is the single scheduling point for AI triage — every
    caller (this route, the AI assistant's create_ticket tool, the email poller)
    goes through it, so every new ticket gets triaged regardless of source."""

    def test_create_schedules_triage_task(self, app, client):
        uid, email, pw = create_user(app, role="admin")
        cust = _make_customer(app)
        try:
            tok = login(client, email, pw).get_json()["access_token"]
            with patch("tasks.triage_tasks.triage_ticket.delay") as mock_delay:
                r = client.post(
                    "/api/tickets/",
                    json={"title": "Needs triage", "customer_id": cust.id},
                    headers=auth_headers(tok),
                    content_type="application/json",
                )
            assert r.status_code == 201
            mock_delay.assert_called_once_with(r.get_json()["id"])
            assert r.get_json()["triage_status"] == "pending"
        finally:
            delete_user(app, uid)
            _del_customer(app, cust.id)

    def test_create_does_not_schedule_triage_when_disabled(self, app, client, monkeypatch):
        monkeypatch.setenv("AI_TRIAGE_ENABLED", "false")
        uid, email, pw = create_user(app, role="admin")
        cust = _make_customer(app)
        try:
            tok = login(client, email, pw).get_json()["access_token"]
            with patch("tasks.triage_tasks.triage_ticket.delay") as mock_delay:
                r = client.post(
                    "/api/tickets/",
                    json={"title": "No triage", "customer_id": cust.id},
                    headers=auth_headers(tok),
                    content_type="application/json",
                )
            assert r.status_code == 201
            mock_delay.assert_not_called()
        finally:
            delete_user(app, uid)
            _del_customer(app, cust.id)


class TestTicketComments:
    def test_add_comment(self, app, client):
        uid, email, pw = create_user(app, role="technician")
        cust = _make_customer(app)
        try:
            tok = login(client, email, pw).get_json()["access_token"]
            r = client.post(
                "/api/tickets/",
                json={"title": "Comment target", "customer_id": cust.id},
                headers=auth_headers(tok),
                content_type="application/json",
            )
            tid = r.get_json()["id"]
            r2 = client.post(
                f"/api/tickets/{tid}/comments",
                json={"body": "Working on it"},
                headers=auth_headers(tok),
                content_type="application/json",
            )
            assert r2.status_code == 201
            assert r2.get_json()["body"] == "Working on it"
        finally:
            delete_user(app, uid)
            _del_customer(app, cust.id)

    def test_add_comment_requires_auth(self, client):
        r = client.post("/api/tickets/nonexistent/comments", json={"body": "x"})
        assert r.status_code == 401

    def test_list_comments(self, app, client):
        uid, email, pw = create_user(app, role="technician")
        cust = _make_customer(app)
        try:
            tok = login(client, email, pw).get_json()["access_token"]
            r = client.post(
                "/api/tickets/",
                json={"title": "List comments", "customer_id": cust.id},
                headers=auth_headers(tok),
                content_type="application/json",
            )
            tid = r.get_json()["id"]
            client.post(f"/api/tickets/{tid}/comments",
                        json={"body": "First"}, headers=auth_headers(tok),
                        content_type="application/json")
            # Comments are embedded in the ticket GET response
            r2 = client.get(f"/api/tickets/{tid}", headers=auth_headers(tok))
            assert r2.status_code == 200
            body = r2.get_json()
            assert "comments" in body
            assert len(body["comments"]) >= 1
        finally:
            delete_user(app, uid)
            _del_customer(app, cust.id)
