"""Email notification utility — reads SMTP config from .env."""
import os
import time
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from utils.usage_tracker import record_event

logger = logging.getLogger(__name__)


def _smtp_send(subject: str, body: str, recipients: list, extra_headers: dict = None) -> bool:
    """Shared SMTP sender. Silently skips if SMTP_HOST not set or recipients empty."""
    smtp_host = os.getenv("SMTP_HOST", "")
    if not smtp_host or not recipients:
        return False
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user or "rmm@localhost")
    _t0 = time.perf_counter()
    try:
        msg = MIMEMultipart()
        msg["From"] = smtp_from
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        if extra_headers:
            for k, v in extra_headers.items():
                msg[k] = v
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            if smtp_port != 25:
                server.starttls()
            if smtp_user:
                server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, recipients, msg.as_string())
        record_event(service="smtp", feature=subject[:100], status="success",
                     latency_ms=int((time.perf_counter() - _t0) * 1000))
        return True
    except Exception as exc:
        logger.warning("SMTP send failed [%s]: %s", subject, exc)
        record_event(service="smtp", feature=subject[:100], status="error",
                     latency_ms=int((time.perf_counter() - _t0) * 1000), error=type(exc).__name__)
        return False


def _ticket_headers(ticket_id: str, in_reply: bool = False) -> dict:
    """Return email threading headers for a ticket thread."""
    mid = f"<ticket-{ticket_id}@rmm>"
    headers = {"Message-ID": mid}
    if in_reply:
        headers["In-Reply-To"] = mid
        headers["References"] = mid
    return headers


def send_alert_notification(rule_name: str, device_hostname: str, message: str, emails: list) -> bool:
    """Send email notification for a triggered alert. Silently skips if SMTP not configured."""
    if not emails:
        return True

    smtp_host = os.getenv("SMTP_HOST", "")
    if not smtp_host:
        logger.info("SMTP_HOST not set — skipping alert notification for: %s", rule_name)
        return False

    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user or "rmm@localhost")

    subject = f"[RMM Alert] {rule_name} — {device_hostname}"
    body = (
        f"RMM Alert Notification\n\n"
        f"Rule:    {rule_name}\n"
        f"Device:  {device_hostname}\n"
        f"Message: {message}\n\n"
        f"---\nThis is an automated notification from RMM System.\n"
    )

    try:
        msg = MIMEMultipart()
        msg["From"] = smtp_from
        msg["To"] = ", ".join(emails)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            if smtp_port != 25:
                server.starttls()
            if smtp_user:
                server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, emails, msg.as_string())

        logger.info("Alert notification sent for rule '%s' to %d recipient(s)", rule_name, len(emails))
        return True
    except Exception as exc:
        logger.warning("Failed to send alert notification for '%s': %s", rule_name, exc)
        return False


def send_account_locked_email(locked_email: str, admin_emails: list) -> bool:
    """Notify all admins when a user account is locked after too many failed attempts."""
    if not admin_emails:
        return True

    smtp_host = os.getenv("SMTP_HOST", "")
    if not smtp_host:
        logger.info("SMTP_HOST not set — skipping account locked notification for: %s", locked_email)
        return False

    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user or "rmm@localhost")

    subject = f"[RMM Security] Account locked: {locked_email}"
    body = (
        f"RMM Security Alert\n\n"
        f"The following account has been locked after 3 consecutive failed login attempts:\n\n"
        f"  Account: {locked_email}\n\n"
        f"The account will auto-unlock after 5 minutes, or an admin can unlock it immediately:\n"
        f"  Admin Panel → Users tab → find the account → click Unlock\n\n"
        f"If this was not a legitimate user, consider reviewing the audit log for suspicious activity.\n\n"
        f"---\nThis is an automated security notification from RMM System.\n"
    )

    try:
        msg = MIMEMultipart()
        msg["From"] = smtp_from
        msg["To"] = ", ".join(admin_emails)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            if smtp_port != 25:
                server.starttls()
            if smtp_user:
                server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, admin_emails, msg.as_string())

        logger.info("Account locked notification sent for '%s' to %d admin(s)", locked_email, len(admin_emails))
        return True
    except Exception as exc:
        logger.warning("Failed to send account locked notification for '%s': %s", locked_email, exc)
        return False


def send_password_reset_email(to_email: str, reset_url: str) -> bool:
    """Send a password reset link to the user. Silently skips if SMTP not configured."""
    smtp_host = os.getenv("SMTP_HOST", "")
    if not smtp_host:
        logger.info("SMTP_HOST not set — skipping password reset email for: %s", to_email)
        return False

    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user or "rmm@localhost")

    subject = "[RMM] Password reset request"
    body = (
        f"RMM Password Reset\n\n"
        f"A password reset was requested for your account ({to_email}).\n\n"
        f"Click the link below to set a new password (valid for 1 hour):\n\n"
        f"  {reset_url}\n\n"
        f"If you did not request this, you can safely ignore this email.\n"
        f"Your password will not change unless you click the link above.\n\n"
        f"---\nThis is an automated notification from RMM System.\n"
    )

    try:
        msg = MIMEMultipart()
        msg["From"] = smtp_from
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            if smtp_port != 25:
                server.starttls()
            if smtp_user:
                server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, [to_email], msg.as_string())

        logger.info("Password reset email sent to '%s'", to_email)
        return True
    except Exception as exc:
        logger.warning("Failed to send password reset email to '%s': %s", to_email, exc)
        return False


def send_login_anomaly_alert(user_email: str, ip: str, admin_emails: list) -> bool:
    """Alert user + admins when login occurs from an unrecognised IP address."""
    smtp_host = os.getenv("SMTP_HOST", "")
    if not smtp_host:
        return False

    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user or "rmm@localhost")

    subject = f"[RMM Security] New login location detected: {user_email}"
    body = (
        f"RMM Security Alert\n\n"
        f"A login to account {user_email} was detected from a new IP address:\n\n"
        f"  IP Address: {ip}\n\n"
        f"If this was you, no action is needed.\n"
        f"If this was NOT you, contact your admin immediately to secure your account.\n\n"
        f"---\nThis is an automated security notification from RMM System.\n"
    )

    recipients = list({user_email} | set(admin_emails))
    try:
        msg = MIMEMultipart()
        msg["From"] = smtp_from
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            if smtp_port != 25:
                server.starttls()
            if smtp_user:
                server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, recipients, msg.as_string())

        logger.info("Login anomaly alert sent for '%s' from IP %s", user_email, ip)
        return True
    except Exception as exc:
        logger.warning("Failed to send login anomaly alert for '%s': %s", user_email, exc)
        return False


def send_account_deactivated_email(to_email: str) -> bool:
    """Notify user their account was auto-deactivated due to 30 days inactivity."""
    smtp_host = os.getenv("SMTP_HOST", "")
    if not smtp_host:
        return False

    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user or "rmm@localhost")

    subject = "[RMM] Your account has been deactivated"
    body = (
        f"RMM Account Notice\n\n"
        f"Your account ({to_email}) has been automatically deactivated due to\n"
        f"30 days of inactivity.\n\n"
        f"To regain access, contact your system administrator to reactivate your account.\n\n"
        f"---\nThis is an automated notification from RMM System.\n"
    )

    try:
        msg = MIMEMultipart()
        msg["From"] = smtp_from
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            if smtp_port != 25:
                server.starttls()
            if smtp_user:
                server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, [to_email], msg.as_string())

        logger.info("Account deactivated notification sent to '%s'", to_email)
        return True
    except Exception as exc:
        logger.warning("Failed to send deactivation email to '%s': %s", to_email, exc)
        return False


def send_dormant_admin_alert(deactivated_emails: list, admin_emails: list) -> bool:
    """Notify admins that dormant accounts were auto-deactivated."""
    if not admin_emails:
        return True
    smtp_host = os.getenv("SMTP_HOST", "")
    if not smtp_host:
        return False

    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user or "rmm@localhost")

    subject = f"[RMM] {len(deactivated_emails)} dormant account(s) deactivated"
    account_list = "\n".join(f"  - {e}" for e in deactivated_emails)
    body = (
        f"RMM System Notice\n\n"
        f"The following account(s) were automatically deactivated due to 30+ days of inactivity:\n\n"
        f"{account_list}\n\n"
        f"To reactivate an account: Admin Panel → Users → Show inactive → Reactivate.\n\n"
        f"---\nThis is an automated notification from RMM System.\n"
    )

    try:
        msg = MIMEMultipart()
        msg["From"] = smtp_from
        msg["To"] = ", ".join(admin_emails)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            if smtp_port != 25:
                server.starttls()
            if smtp_user:
                server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, admin_emails, msg.as_string())

        logger.info("Dormant admin alert sent: %d account(s) deactivated", len(deactivated_emails))
        return True
    except Exception as exc:
        logger.warning("Failed to send dormant admin alert: %s", exc)
        return False


def send_password_expiry_warning(to_email: str, days_left: int) -> bool:
    """Warn user their password expires in N days."""
    smtp_host = os.getenv("SMTP_HOST", "")
    if not smtp_host:
        return False

    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user or "rmm@localhost")

    subject = f"[RMM] Your password expires in {days_left} day(s)"
    body = (
        f"RMM Password Expiry Notice\n\n"
        f"Your password for account {to_email} will expire in {days_left} day(s).\n\n"
        f"Please log in and change your password before it expires to avoid being locked out.\n"
        f"Go to: My Profile → Change Password\n\n"
        f"---\nThis is an automated notification from RMM System.\n"
    )

    try:
        msg = MIMEMultipart()
        msg["From"] = smtp_from
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            if smtp_port != 25:
                server.starttls()
            if smtp_user:
                server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, [to_email], msg.as_string())

        logger.info("Password expiry warning sent to '%s' (%d days left)", to_email, days_left)
        return True
    except Exception as exc:
        logger.warning("Failed to send expiry warning to '%s': %s", to_email, exc)
        return False


# ── Ticket notifications ───────────────────────────────────────────────────────

def _ticket_subject(ticket_id: str, title: str, prefix: str = "[Support]") -> str:
    return f"{prefix} [Ticket #{ticket_id[:8].upper()}] {title}"


def send_ticket_created_client(ticket_title: str, ticket_id: str, priority: str, client_emails: list) -> bool:
    """Confirm to client(s) that their ticket was received."""
    subject = _ticket_subject(ticket_id, ticket_title)
    body = (
        f"Your support request has been received.\n\n"
        f"  Subject:  {ticket_title}\n"
        f"  Priority: {priority.capitalize()}\n"
        f"  Ref:      {ticket_id[:8].upper()}\n\n"
        f"Our team will review your request and respond shortly.\n\n"
        f"---\nRMM Support System\n"
    )
    ok = _smtp_send(subject, body, client_emails, _ticket_headers(ticket_id))
    if ok:
        logger.info("Ticket created confirmation sent to %d client(s) for ticket %s", len(client_emails), ticket_id)
    return ok


def send_email_ticket_confirmation(ticket_title: str, ticket_id: str, requester_email: str) -> bool:
    """Send auto-reply to email sender confirming ticket creation."""
    subject = _ticket_subject(ticket_id, ticket_title)
    body = (
        f"Thank you for contacting support.\n\n"
        f"Your request has been logged:\n\n"
        f"  Subject: {ticket_title}\n"
        f"  Ref:     {ticket_id[:8].upper()}\n\n"
        f"To add information or reply, simply reply to this email.\n"
        f"Our team will respond shortly.\n\n"
        f"---\nRMM Support System\n"
    )
    ok = _smtp_send(subject, body, [requester_email], _ticket_headers(ticket_id))
    if ok:
        logger.info("Email ticket confirmation sent to '%s' for ticket %s", requester_email, ticket_id)
    return ok


def send_ticket_assigned(ticket_title: str, ticket_id: str, customer_name: str, priority: str, assignee_email: str) -> bool:
    """Notify technician they were assigned a ticket."""
    subject = _ticket_subject(ticket_id, ticket_title, "[RMM]")
    body = (
        f"A ticket has been assigned to you.\n\n"
        f"  Subject:  {ticket_title}\n"
        f"  Customer: {customer_name}\n"
        f"  Priority: {priority.capitalize()}\n"
        f"  Ref:      {ticket_id[:8].upper()}\n\n"
        f"Log in to the RMM dashboard to view and action this ticket.\n\n"
        f"---\nRMM System\n"
    )
    ok = _smtp_send(subject, body, [assignee_email], _ticket_headers(ticket_id))
    if ok:
        logger.info("Ticket assigned notification sent to '%s' for ticket %s", assignee_email, ticket_id)
    return ok


def send_ticket_resolved_client(ticket_title: str, ticket_id: str, client_emails: list, requester_email: str = None) -> bool:
    """Notify client(s) their ticket was resolved."""
    subject = _ticket_subject(ticket_id, ticket_title)
    body = (
        f"Your support ticket has been resolved.\n\n"
        f"  Subject: {ticket_title}\n"
        f"  Ref:     {ticket_id[:8].upper()}\n\n"
        f"If you are still experiencing issues, please submit a new support request\n"
        f"or reply to this email to reopen the ticket.\n\n"
        f"---\nRMM Support System\n"
    )
    recipients = list({*(client_emails or []), *([requester_email] if requester_email else [])})
    ok = _smtp_send(subject, body, recipients, _ticket_headers(ticket_id, in_reply=True))
    if ok:
        logger.info("Ticket resolved notification sent to %d recipient(s) for ticket %s", len(recipients), ticket_id)
    return ok


def send_ticket_comment_to_client(ticket_title: str, ticket_id: str, comment_body: str, client_emails: list, requester_email: str = None) -> bool:
    """Notify client(s) and/or requester that staff replied."""
    subject = _ticket_subject(ticket_id, ticket_title)
    body = (
        f"There is a new update on your support ticket.\n\n"
        f"  Subject: {ticket_title}\n"
        f"  Ref:     {ticket_id[:8].upper()}\n\n"
        f"Staff reply:\n"
        f"  {comment_body}\n\n"
        f"Reply to this email to respond, or log in to the support portal.\n\n"
        f"---\nRMM Support System\n"
    )
    recipients = list({*(client_emails or []), *([requester_email] if requester_email else [])})
    if not recipients:
        return False
    ok = _smtp_send(subject, body, recipients, _ticket_headers(ticket_id, in_reply=True))
    if ok:
        logger.info("Comment notification sent to %d recipient(s) for ticket %s", len(recipients), ticket_id)
    return ok


def send_ai_ticket_resolution(ticket_title: str, ticket_id: str, draft_reply: str, client_emails: list,
                              requester_email: str = None, auto_close_days: int = 7) -> bool:
    """Send the AI's drafted reply to the customer for an auto-resolved ticket.
    Threaded as a reply (in_reply=True) so a customer reply is recognized by
    poll_support_inbox's _find_ticket() and reopens the ticket."""
    subject = _ticket_subject(ticket_id, ticket_title)
    body = (
        f"Your support ticket has been resolved.\n\n"
        f"  Subject: {ticket_title}\n"
        f"  Ref:     {ticket_id[:8].upper()}\n\n"
        f"{draft_reply}\n\n"
        f"If this didn't resolve your issue, simply reply to this email and a member of "
        f"our team will take over.\n\n"
        f"This ticket will automatically close in {auto_close_days} day(s) if we don't hear back.\n\n"
        f"---\nRMM Support System\n"
    )
    recipients = list({*(client_emails or []), *([requester_email] if requester_email else [])})
    if not recipients:
        return False
    ok = _smtp_send(subject, body, recipients, _ticket_headers(ticket_id, in_reply=True))
    if ok:
        logger.info("AI resolution reply sent to %d recipient(s) for ticket %s", len(recipients), ticket_id)
    return ok


def send_ticket_escalated_notification(ticket, reason: str) -> bool:
    """Internal-facing notification when AI triage escalates a ticket to a human
    (or a reply reopens an AI-resolved one). Recipient is the ticket's assignee
    if set, else TRIAGE_ESCALATION_FALLBACK_EMAILS — there's no "department lead"
    lookup in this codebase yet to route to instead."""
    recipients = []
    if ticket.assignee_id:
        from models.user import User
        from extensions import db
        assignee = db.session.get(User, ticket.assignee_id)
        if assignee and assignee.email:
            recipients = [assignee.email]
    if not recipients:
        fallback = os.getenv("TRIAGE_ESCALATION_FALLBACK_EMAILS", "")
        recipients = [e.strip() for e in fallback.split(",") if e.strip()]
    if not recipients:
        return False

    subject = _ticket_subject(ticket.id, ticket.title, "[RMM AI Triage]")
    body = (
        f"A ticket needs human review.\n\n"
        f"  Subject:  {ticket.title}\n"
        f"  Ref:      {ticket.id[:8].upper()}\n"
        f"  Reason:   {reason}\n"
        f"  Category: {ticket.ai_suggested_category or 'uncategorized'}"
        f" (confidence: {ticket.ai_confidence if ticket.ai_confidence is not None else 'n/a'})\n\n"
        f"Log in to the RMM dashboard to review and respond.\n\n"
        f"---\nRMM System\n"
    )
    ok = _smtp_send(subject, body, recipients, _ticket_headers(ticket.id))
    if ok:
        logger.info("Escalation notification sent to %d recipient(s) for ticket %s", len(recipients), ticket.id)
    return ok


def send_ticket_comment_to_assignee(ticket_title: str, ticket_id: str, comment_body: str, assignee_email: str) -> bool:
    """Notify assignee that the client replied to their ticket."""
    subject = _ticket_subject(ticket_id, ticket_title, "[RMM]")
    body = (
        f"The client has replied on a ticket assigned to you.\n\n"
        f"  Subject: {ticket_title}\n"
        f"  Ref:     {ticket_id[:8].upper()}\n\n"
        f"Client reply:\n"
        f"  {comment_body}\n\n"
        f"Log in to the RMM dashboard to respond.\n\n"
        f"---\nRMM System\n"
    )
    ok = _smtp_send(subject, body, [assignee_email], _ticket_headers(ticket_id, in_reply=True))
    if ok:
        logger.info("Client reply notification sent to '%s' for ticket %s", assignee_email, ticket_id)
    return ok
