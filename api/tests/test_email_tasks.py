"""Tests for tasks/email_tasks.py::poll_support_inbox and its parsing helpers
(audits/testing_audit.md Finding C3 — the last remaining untested task file).
Never connects to a real IMAP server — imaplib.IMAP4_SSL is always mocked."""
import email as email_lib
import uuid
from email.message import EmailMessage
from unittest.mock import MagicMock, patch

import tasks._app_singleton as app_singleton
import tasks.email_tasks as email_tasks
from conftest import create_user, delete_user


class TestDecodeStr:
    def test_plain_ascii(self):
        assert email_tasks._decode_str("Hello World") == "Hello World"

    def test_empty(self):
        assert email_tasks._decode_str("") == ""


class TestParseFrom:
    def test_extracts_name_and_email(self):
        result = email_tasks._parse_from("Jane Doe <jane@example.com>")
        assert result == {"name": "Jane Doe", "email": "jane@example.com"}

    def test_lowercases_email(self):
        result = email_tasks._parse_from("Bob <BOB@EXAMPLE.COM>")
        assert result["email"] == "bob@example.com"

    def test_missing_from_header(self):
        assert email_tasks._parse_from("") == {"name": "", "email": ""}


class TestExtractBody:
    def test_plain_text_message(self):
        msg = EmailMessage()
        msg.set_content("Hello, this is the body.")
        assert email_tasks._extract_body(msg) == "Hello, this is the body."

    def test_strips_quoted_reply_lines(self):
        msg = EmailMessage()
        msg.set_content("My reply.\n\nOn Mon, Jan 1, 2026, Jane wrote:\n> original message")
        body = email_tasks._extract_body(msg)
        assert "My reply." in body
        assert "original message" not in body

    def test_strips_gt_prefixed_lines(self):
        msg = EmailMessage()
        msg.set_content("New text\n> quoted line 1\n> quoted line 2")
        body = email_tasks._extract_body(msg)
        assert "New text" in body
        assert "quoted line" not in body


class TestFindCustomerId:
    def test_finds_customer_from_known_user_email(self, app):
        with app.app_context():
            uid, email, _ = create_user(app, role="client")
            from extensions import db
            from models.customer import Customer
            cust = Customer(name=f"EmailCo-{uuid.uuid4().hex[:6]}", slug=f"ec-{uuid.uuid4().hex[:6]}", is_active=True)
            db.session.add(cust)
            db.session.commit()
            from models.user import User
            user = db.session.get(User, uid)
            user.customer_id = cust.id
            db.session.commit()
            try:
                result = email_tasks._find_customer_id(email)
                assert result == cust.id
            finally:
                Customer.query.filter_by(id=cust.id).delete()
                db.session.commit()
                delete_user(app, uid)

    def test_unknown_sender_falls_back_to_default_env_var(self, app, monkeypatch):
        monkeypatch.setenv("DEFAULT_INBOUND_CUSTOMER_ID", "fallback-cust-id")
        with app.app_context():
            result = email_tasks._find_customer_id("nobody@nowhere.invalid")
        assert result == "fallback-cust-id"

    def test_unknown_sender_no_default_returns_empty(self, app, monkeypatch):
        monkeypatch.delenv("DEFAULT_INBOUND_CUSTOMER_ID", raising=False)
        with app.app_context():
            result = email_tasks._find_customer_id("nobody@nowhere.invalid")
        assert result == ""


def _fake_email_bytes(*, from_addr, subject, body, message_id=None, in_reply_to=None):
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["Subject"] = subject
    msg["Message-ID"] = message_id or f"<{uuid.uuid4().hex}@sender.example>"
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    msg.set_content(body)
    return msg.as_bytes()


class TestPollSupportInbox:
    def test_returns_early_when_not_configured(self, app, monkeypatch):
        monkeypatch.delenv("SUPPORT_IMAP_HOST", raising=False)
        app_singleton._app = app
        with patch("tasks.email_tasks.imaplib.IMAP4_SSL") as mock_imap:
            email_tasks.poll_support_inbox()
        mock_imap.assert_not_called()

    def test_creates_new_ticket_from_unseen_email(self, app, monkeypatch):
        monkeypatch.setenv("SUPPORT_IMAP_HOST", "imap.example.com")
        monkeypatch.setenv("SUPPORT_IMAP_USER", "support@example.com")
        monkeypatch.setenv("SUPPORT_IMAP_PASSWORD", "secret")
        monkeypatch.setenv("DEFAULT_INBOUND_CUSTOMER_ID", "")
        app_singleton._app = app

        with app.app_context():
            from extensions import db
            from models.customer import Customer
            cust = Customer(name=f"InboxCo-{uuid.uuid4().hex[:6]}", slug=f"ic-{uuid.uuid4().hex[:6]}", is_active=True)
            db.session.add(cust)
            db.session.commit()
            cust_id = cust.id

        raw = _fake_email_bytes(
            from_addr="customer@external.example", subject="Printer is broken",
            body="It won't turn on.",
        )
        mock_mail = MagicMock()
        mock_mail.search.return_value = ("OK", [b"1"])
        mock_mail.fetch.return_value = ("OK", [(b"1 (RFC822 {n}", raw)])

        ticket_id = None
        try:
            with patch("tasks.email_tasks.imaplib.IMAP4_SSL", return_value=mock_mail), \
                 patch("tasks.email_tasks.os.getenv", side_effect=lambda k, d="": {
                     "SUPPORT_IMAP_HOST": "imap.example.com",
                     "SUPPORT_IMAP_PORT": "993",
                     "SUPPORT_IMAP_USER": "support@example.com",
                     "SUPPORT_IMAP_PASSWORD": "secret",
                     "DEFAULT_INBOUND_CUSTOMER_ID": cust_id,
                 }.get(k, d)), \
                 patch("utils.notifications.send_email_ticket_confirmation"):
                email_tasks.poll_support_inbox()

            mock_mail.login.assert_called_once_with("support@example.com", "secret")
            mock_mail.logout.assert_called_once()

            with app.app_context():
                from models.ticket import Ticket
                ticket = Ticket.query.filter_by(customer_id=cust_id).first()
                assert ticket is not None
                assert ticket.title == "Printer is broken"
                assert ticket.requester_email == "customer@external.example"
                assert ticket.source == "email"
                ticket_id = ticket.id
        finally:
            with app.app_context():
                from extensions import db
                from models.ticket import Ticket
                from models.customer import Customer
                if ticket_id:
                    Ticket.query.filter_by(id=ticket_id).delete()
                Customer.query.filter_by(id=cust_id).delete()
                db.session.commit()

    def test_unknown_sender_falls_back_to_unassigned_inbound_customer(self, app, monkeypatch):
        """DEFAULT_INBOUND_CUSTOMER_ID unset + UNASSIGNED_INBOUND_CUSTOMER_ID set
        -> a ticket is still created (never silently dropped) against the catch-all
        customer, which a human can reassign afterward."""
        monkeypatch.setenv("SUPPORT_IMAP_HOST", "imap.example.com")
        monkeypatch.setenv("SUPPORT_IMAP_USER", "support@example.com")
        monkeypatch.setenv("SUPPORT_IMAP_PASSWORD", "secret")
        app_singleton._app = app

        with app.app_context():
            from extensions import db
            from models.customer import Customer
            cust = Customer(name=f"UnassignedCo-{uuid.uuid4().hex[:6]}", slug=f"ua-{uuid.uuid4().hex[:6]}",
                            is_active=True)
            db.session.add(cust)
            db.session.commit()
            cust_id = cust.id

        raw = _fake_email_bytes(
            from_addr="unknown@external.example", subject="Need help",
            body="Something is broken.",
        )
        mock_mail = MagicMock()
        mock_mail.search.return_value = ("OK", [b"1"])
        mock_mail.fetch.return_value = ("OK", [(b"1 (RFC822 {n}", raw)])

        ticket_id = None
        try:
            with patch("tasks.email_tasks.imaplib.IMAP4_SSL", return_value=mock_mail), \
                 patch("tasks.email_tasks.os.getenv", side_effect=lambda k, d="": {
                     "SUPPORT_IMAP_HOST": "imap.example.com",
                     "SUPPORT_IMAP_PORT": "993",
                     "SUPPORT_IMAP_USER": "support@example.com",
                     "SUPPORT_IMAP_PASSWORD": "secret",
                     "DEFAULT_INBOUND_CUSTOMER_ID": "",
                     "UNASSIGNED_INBOUND_CUSTOMER_ID": cust_id,
                     "AI_TRIAGE_ENABLED": "false",
                 }.get(k, d)), \
                 patch("utils.notifications.send_email_ticket_confirmation"):
                email_tasks.poll_support_inbox()

            with app.app_context():
                from models.ticket import Ticket
                ticket = Ticket.query.filter_by(customer_id=cust_id).first()
                assert ticket is not None
                assert ticket.requester_email == "unknown@external.example"
                ticket_id = ticket.id
        finally:
            with app.app_context():
                from extensions import db
                from models.ticket import Ticket
                from models.customer import Customer
                if ticket_id:
                    Ticket.query.filter_by(id=ticket_id).delete()
                Customer.query.filter_by(id=cust_id).delete()
                db.session.commit()

    def test_reply_to_auto_resolved_ticket_reopens_and_notifies(self, app, monkeypatch):
        """A customer reply to an AI-auto-resolved ticket must reopen it and route
        to a human — it must NOT re-trigger triage."""
        monkeypatch.setenv("SUPPORT_IMAP_HOST", "imap.example.com")
        monkeypatch.setenv("SUPPORT_IMAP_USER", "support@example.com")
        monkeypatch.setenv("SUPPORT_IMAP_PASSWORD", "secret")
        app_singleton._app = app

        with app.app_context():
            from extensions import db
            from models.customer import Customer
            from models.ticket import Ticket
            cust = Customer(name=f"ReopenCo-{uuid.uuid4().hex[:6]}", slug=f"ro-{uuid.uuid4().hex[:6]}",
                            is_active=True)
            db.session.add(cust)
            db.session.commit()
            ticket = Ticket(
                title="Already resolved by AI", customer_id=cust.id, status="resolved",
                auto_resolved=True, triage_status="auto_resolved",
                requester_email="customer@external.example",
                email_thread_id="<original-msg@sender.example>",
            )
            db.session.add(ticket)
            db.session.commit()
            cust_id, ticket_id = cust.id, ticket.id

        raw = _fake_email_bytes(
            from_addr="customer@external.example", subject="Re: Already resolved by AI",
            body="This did not fix it.", in_reply_to="<original-msg@sender.example>",
        )
        mock_mail = MagicMock()
        mock_mail.search.return_value = ("OK", [b"1"])
        mock_mail.fetch.return_value = ("OK", [(b"1 (RFC822 {n}", raw)])

        try:
            with patch("tasks.email_tasks.imaplib.IMAP4_SSL", return_value=mock_mail), \
                 patch("tasks.triage_tasks.triage_ticket.delay") as mock_triage_delay:
                email_tasks.poll_support_inbox()

            mock_triage_delay.assert_not_called()

            with app.app_context():
                from models.ticket import Ticket
                from models.ticket import TicketComment
                refreshed = Ticket.query.filter_by(id=ticket_id).first()
                assert refreshed.status == "in_progress"
                assert refreshed.auto_resolved is False
                assert refreshed.triage_status == "reopened"
                comments = TicketComment.query.filter_by(ticket_id=ticket_id).all()
                assert any("did not fix it" in (c.body or "") for c in comments)
        finally:
            with app.app_context():
                from extensions import db
                from models.ticket import Ticket, TicketComment
                from models.customer import Customer
                TicketComment.query.filter_by(ticket_id=ticket_id).delete()
                Ticket.query.filter_by(id=ticket_id).delete()
                Customer.query.filter_by(id=cust_id).delete()
                db.session.commit()

    def test_no_unseen_messages_is_a_clean_noop(self, app, monkeypatch):
        monkeypatch.setenv("SUPPORT_IMAP_HOST", "imap.example.com")
        monkeypatch.setenv("SUPPORT_IMAP_USER", "support@example.com")
        monkeypatch.setenv("SUPPORT_IMAP_PASSWORD", "secret")
        app_singleton._app = app

        mock_mail = MagicMock()
        mock_mail.search.return_value = ("OK", [b""])

        with patch("tasks.email_tasks.imaplib.IMAP4_SSL", return_value=mock_mail):
            email_tasks.poll_support_inbox()

        mock_mail.fetch.assert_not_called()
        mock_mail.logout.assert_called_once()
