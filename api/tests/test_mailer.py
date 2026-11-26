"""utils/mailer.py: the one SMTP sender, and the callers that use it.

A fake smtplib.SMTP records what would have been sent, so nothing leaves the machine. Includes the regression test for
invoice emails, which read SMTP_PASS while every other email (and .env.example) used SMTP_PASSWORD, so they signed in
with an empty password."""
import email
import logging

import pytest

import utils.mailer as mailer
from conftest import create_user, login, auth_headers
from test_billing import _cleanup, _make_customer, _make_invoice


class FakeSMTP:
    sent = []  # one dict per connection, newest last

    def __init__(self, host, port, timeout=None):
        self.rec = {"host": host, "port": port, "timeout": timeout, "tls": False, "login": None, "mail": None}
        FakeSMTP.sent.append(self.rec)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        pass

    def starttls(self):
        self.rec["tls"] = True

    def login(self, user, password):
        self.rec["login"] = (user, password)

    def sendmail(self, sender, recipients, text):
        self.rec["mail"] = (sender, list(recipients), email.message_from_string(text))


class FailingSMTP(FakeSMTP):
    def sendmail(self, *a):
        raise OSError("connection reset")


@pytest.fixture
def smtp(monkeypatch):
    for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_PASS", "SMTP_FROM"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(mailer, "_warned_old_name", False)
    FakeSMTP.sent = []
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


class TestSettings:
    def test_off_without_host(self, smtp):
        assert mailer.smtp_settings() is None

    def test_defaults_and_from_fallbacks(self, smtp, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "mail.example.com")
        assert mailer.smtp_settings() == {"host": "mail.example.com", "port": 587, "user": "", "password": "", "from": "rmm@localhost"}
        assert mailer.smtp_settings(default_from="billing@localhost")["from"] == "billing@localhost"
        monkeypatch.setenv("SMTP_USER", "me@example.com")
        assert mailer.smtp_settings()["from"] == "me@example.com"
        monkeypatch.setenv("SMTP_FROM", "alerts@example.com")
        assert mailer.smtp_settings()["from"] == "alerts@example.com"

    def test_password_name_and_old_fallback(self, smtp, monkeypatch, caplog):
        monkeypatch.setenv("SMTP_HOST", "mail.example.com")
        monkeypatch.setenv("SMTP_PASSWORD", "right")
        monkeypatch.setenv("SMTP_PASS", "old")
        assert mailer.smtp_settings()["password"] == "right", "SMTP_PASSWORD wins"
        monkeypatch.delenv("SMTP_PASSWORD")
        with caplog.at_level(logging.WARNING, logger="utils.mailer"):
            assert mailer.smtp_settings()["password"] == "old", "the old name still works"
            mailer.smtp_settings()
        assert [r.message for r in caplog.records].count("SMTP_PASS is deprecated: rename it to SMTP_PASSWORD in .env") == 1


class TestSend:
    def test_plain_message_with_tls_and_login(self, smtp, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "mail.example.com")
        monkeypatch.setenv("SMTP_USER", "me@example.com")
        monkeypatch.setenv("SMTP_PASSWORD", "pw")
        mailer.send_email(mailer.smtp_settings(), "Hello", "Body text", ["a@x.com", "b@x.com"], extra_headers={"Message-ID": "<m1@rmm>"})
        rec = smtp.sent[-1]
        assert (rec["host"], rec["port"], rec["timeout"], rec["tls"], rec["login"]) == ("mail.example.com", 587, 15, True, ("me@example.com", "pw"))
        sender, to, msg = rec["mail"]
        assert sender == "me@example.com" and to == ["a@x.com", "b@x.com"]
        assert msg["To"] == "a@x.com, b@x.com" and msg["Subject"] == "Hello" and msg["Message-ID"] == "<m1@rmm>"
        assert msg.get_payload()[0].get_content_type() == "text/plain"

    def test_port_25_no_tls_and_no_login_without_user(self, smtp, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "relay.local")
        monkeypatch.setenv("SMTP_PORT", "25")
        mailer.send_email(mailer.smtp_settings(), "s", "b", ["a@x.com"])
        assert smtp.sent[-1]["tls"] is False and smtp.sent[-1]["login"] is None

    def test_html_with_attachment(self, smtp, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "mail.example.com")
        mailer.send_email(mailer.smtp_settings(), "Invoice", "<p>Hi</p>", ["c@x.com"], subtype="html", timeout=20,
                          attachments=[("invoice-1.pdf", b"%PDF-1.4 test", "application/pdf")])
        rec = smtp.sent[-1]
        parts = rec["mail"][2].get_payload()
        assert rec["timeout"] == 20
        assert parts[0].get_content_type() == "text/html"
        assert parts[1].get_content_type() == "application/pdf"
        assert parts[1].get_filename() == "invoice-1.pdf"
        assert parts[1].get_payload(decode=True) == b"%PDF-1.4 test"

    def test_failure_raises(self, smtp, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "mail.example.com")
        monkeypatch.setattr(mailer.smtplib, "SMTP", FailingSMTP)
        with pytest.raises(OSError):
            mailer.send_email(mailer.smtp_settings(), "s", "b", ["a@x.com"])


class TestCallers:
    def test_notification_sends_and_reports(self, smtp, monkeypatch):
        from utils.notifications import send_password_reset_email
        assert send_password_reset_email("u@x.com", "https://r") is False, "off without SMTP_HOST"
        monkeypatch.setenv("SMTP_HOST", "mail.example.com")
        assert send_password_reset_email("u@x.com", "https://r") is True
        _, to, msg = smtp.sent[-1]["mail"]
        assert to == ["u@x.com"] and msg["Subject"] == "[RMM] Password reset request"
        assert "https://r" in msg.get_payload()[0].get_payload()
        monkeypatch.setattr(mailer.smtplib, "SMTP", FailingSMTP)
        assert send_password_reset_email("u@x.com", "https://r") is False, "a failure is reported, not raised"

    def test_invoice_email_uses_smtp_password(self, smtp, app, client, monkeypatch):
        """Regression: the invoice email must sign in with SMTP_PASSWORD (it read SMTP_PASS)."""
        monkeypatch.setenv("SMTP_HOST", "mail.example.com")
        monkeypatch.setenv("SMTP_USER", "billing@example.com")
        monkeypatch.setenv("SMTP_PASSWORD", "the-real-password")
        uid, em, pw = create_user(app, role="admin")
        cust = _make_customer(app, email="customer@example.com")
        inv = _make_invoice(app, cust.id)
        try:
            token = login(client, em, pw).get_json()["access_token"]
            r = client.post(f"/api/billing/invoices/{inv.id}/send-email", headers=auth_headers(token))
            assert r.status_code == 200, r.get_json()
            rec = smtp.sent[-1]
            assert rec["login"] == ("billing@example.com", "the-real-password")
            assert rec["timeout"] == 20
            sender, to, msg = rec["mail"]
            assert sender == "billing@example.com" and to == ["customer@example.com"]
            parts = msg.get_payload()
            assert parts[0].get_content_type() == "text/html"
            assert parts[1].get_content_type() == "application/pdf"
            assert parts[1].get_payload(decode=True)[:4] == b"%PDF"
        finally:
            _cleanup(app, user_ids=[uid], invoice_ids=[inv.id], customer_ids=[cust.id])
