"""SMTP email: the one place that reads the SMTP_* settings and talks to the mail server.

Every email the API sends (alerts, security notices, tickets, invoices) goes through send_email(), so a change of mail
provider, port or encryption is made here once. Callers keep their own wording, logging and error handling.

Settings (.env): SMTP_HOST (unset = email off), SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD, SMTP_FROM.
"""
import os
import logging
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)
_warned_old_name = False


def _password() -> str:
    """SMTP_PASSWORD; the old name SMTP_PASS (read only by invoice emails before) still works, with a warning."""
    global _warned_old_name
    value = os.getenv("SMTP_PASSWORD", "")
    if not value and os.getenv("SMTP_PASS"):
        if not _warned_old_name:
            logger.warning("SMTP_PASS is deprecated: rename it to SMTP_PASSWORD in .env")
            _warned_old_name = True
        value = os.getenv("SMTP_PASS", "")
    return value


def smtp_settings(default_from: str = "rmm@localhost"):
    """The SMTP settings as a dict, or None when SMTP_HOST is not set (email is off)."""
    host = os.getenv("SMTP_HOST", "")
    if not host:
        return None
    user = os.getenv("SMTP_USER", "")
    return {
        "host": host,
        "port": int(os.getenv("SMTP_PORT", "587")),
        "user": user,
        "password": _password(),
        "from": os.getenv("SMTP_FROM", user or default_from),
    }


def send_email(cfg: dict, subject: str, body: str, recipients: list, *, subtype: str = "plain",
               extra_headers: dict = None, attachments: list = (), timeout: int = 15) -> None:
    """Send one message to every address in recipients. Raises on any failure; the caller decides what that means.

    cfg: smtp_settings(). attachments: (filename, bytes, mime type such as "application/pdf") tuples.
    STARTTLS is used on every port except 25; login only when SMTP_USER is set.
    """
    msg = MIMEMultipart()
    msg["From"] = cfg["from"]
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    for k, v in (extra_headers or {}).items():
        msg[k] = v
    msg.attach(MIMEText(body, subtype))
    for filename, data, mime in attachments:
        main, sub = mime.split("/", 1)
        part = MIMEBase(main, sub)
        part.set_payload(data)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
        msg.attach(part)

    with smtplib.SMTP(cfg["host"], cfg["port"], timeout=timeout) as server:
        server.ehlo()
        if cfg["port"] != 25:
            server.starttls()
        if cfg["user"]:
            server.login(cfg["user"], cfg["password"])
        server.sendmail(cfg["from"], list(recipients), msg.as_string())
