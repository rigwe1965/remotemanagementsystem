"""Email-to-ticket: polls support inbox and creates/threads tickets."""
import imaplib
import email as email_lib
import os
import re
import logging
from datetime import datetime, timezone, timedelta
from email.header import decode_header as _raw_decode
from email.utils import parseaddr

from tasks.celery_app import celery

logger = logging.getLogger(__name__)

_app = None


def _get_app():
    global _app
    if _app is None:
        from app import create_app
        _app = create_app()
    return _app

_TICKET_REF_RE = re.compile(r"\[Ticket #([A-F0-9]{8})\]", re.IGNORECASE)
_SLA_HOURS = {"critical": 4, "high": 8, "medium": 24, "low": 72}


# ── Parsing helpers ────────────────────────────────────────────────────────────

def _decode_str(val: str) -> str:
    if not val:
        return ""
    parts = _raw_decode(val)
    result = []
    for part, enc in parts:
        if isinstance(part, bytes):
            result.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            result.append(str(part))
    return "".join(result).strip()


def _parse_from(from_header: str) -> dict:
    name, addr = parseaddr(from_header or "")
    return {"name": name.strip(), "email": addr.strip().lower()}


def _extract_body(msg) -> str:
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in cd:
                charset = part.get_content_charset() or "utf-8"
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode(charset, errors="replace")
                break
    else:
        charset = msg.get_content_charset() or "utf-8"
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode(charset, errors="replace")

    # Strip quoted reply lines
    lines = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            continue
        lower = stripped.lower()
        if lower.startswith("on ") and "wrote:" in lower:
            break
        lines.append(line)

    return "\n".join(lines).strip()[:5000]


def _find_ticket(in_reply_to: str, references: str, subject: str):
    from extensions import db
    from models.ticket import Ticket

    all_refs = []
    if in_reply_to:
        all_refs.append(in_reply_to.strip())
    if references:
        all_refs.extend(references.split())

    for ref in all_refs:
        ref = ref.strip("<> ")
        if not ref:
            continue
        # Our outbound Message-IDs look like ticket-{uuid}@rmm
        if ref.startswith("ticket-"):
            tid = ref.split("@")[0][len("ticket-"):]
            t = db.session.get(Ticket, tid)
            if t:
                return t
        # Match against stored email_thread_id
        t = Ticket.query.filter_by(email_thread_id=f"<{ref}>").first() or \
            Ticket.query.filter_by(email_thread_id=ref).first()
        if t:
            return t

    # Subject [Ticket #XXXXXXXX] fallback
    m = _TICKET_REF_RE.search(subject or "")
    if m:
        short = m.group(1).lower()
        t = Ticket.query.filter(Ticket.id.like(f"{short}%")).first()
        if t:
            return t

    return None


def _find_customer_id(sender_email: str):
    from models.user import User
    user = User.query.filter_by(email=sender_email, is_active=True).first()
    if user and user.customer_id:
        return user.customer_id
    return os.getenv("DEFAULT_INBOUND_CUSTOMER_ID", "")


# ── Celery task ────────────────────────────────────────────────────────────────

@celery.task(name="tasks.email_tasks.poll_support_inbox", bind=True, max_retries=2)
def poll_support_inbox(self):
    imap_host = os.getenv("SUPPORT_IMAP_HOST", "")
    if not imap_host:
        return  # not configured

    imap_port = int(os.getenv("SUPPORT_IMAP_PORT", "993"))
    imap_user = os.getenv("SUPPORT_IMAP_USER", "")
    imap_pass = os.getenv("SUPPORT_IMAP_PASSWORD", "")

    if not imap_user or not imap_pass:
        logger.warning("SUPPORT_IMAP_USER or SUPPORT_IMAP_PASSWORD not set — skipping")
        return

    from extensions import db
    from models.ticket import Ticket, TicketComment
    from utils.notifications import (
        send_email_ticket_confirmation,
        send_ticket_comment_to_assignee,
        send_ticket_comment_to_client,
    )

    with _get_app().app_context():
        try:
            mail = imaplib.IMAP4_SSL(imap_host, imap_port)
            mail.login(imap_user, imap_pass)
            mail.select("INBOX")

            _, msg_ids_raw = mail.search(None, "UNSEEN")
            msg_ids = msg_ids_raw[0].split()
            if not msg_ids:
                mail.logout()
                return

            logger.info("Email poller: %d unseen message(s)", len(msg_ids))

            for mid in msg_ids:
                try:
                    _, data = mail.fetch(mid, "(RFC822)")
                    raw = data[0][1]
                    msg = email_lib.message_from_bytes(raw)

                    message_id  = msg.get("Message-ID", "").strip()
                    in_reply_to = msg.get("In-Reply-To", "").strip()
                    references  = msg.get("References", "").strip()
                    subject     = _decode_str(msg.get("Subject", "(No subject)"))
                    sender      = _parse_from(msg.get("From", ""))
                    body        = _extract_body(msg)

                    if not sender["email"]:
                        mail.store(mid, "+FLAGS", "\\Seen")
                        continue

                    existing = _find_ticket(in_reply_to, references, subject)

                    if existing:
                        # Add as comment on existing ticket
                        comment = TicketComment(
                            ticket_id=existing.id,
                            author_id=None,
                            author_email=sender["email"],
                            body=body or "(empty reply)",
                            is_internal=False,
                        )
                        db.session.add(comment)
                        db.session.commit()

                        try:
                            if existing.assignee_id:
                                from models.user import User
                                assignee = db.session.get(User, existing.assignee_id)
                                if assignee and assignee.email:
                                    send_ticket_comment_to_assignee(
                                        existing.title, existing.id,
                                        body[:300], assignee.email,
                                    )
                        except Exception:
                            pass

                        logger.info("Added email reply as comment on ticket %s", existing.id)

                    else:
                        # Create new ticket
                        customer_id = _find_customer_id(sender["email"])
                        if not customer_id:
                            logger.warning(
                                "No customer found for %s and DEFAULT_INBOUND_CUSTOMER_ID not set — skipping",
                                sender["email"],
                            )
                            mail.store(mid, "+FLAGS", "\\Seen")
                            continue

                        # Strip Re:/Fwd: prefixes and [Ticket #xxx] from subject
                        clean_subject = re.sub(r"^(re|fwd|fw):\s*", "", subject, flags=re.IGNORECASE).strip()
                        clean_subject = _TICKET_REF_RE.sub("", clean_subject).strip() or "(No subject)"

                        ticket = Ticket(
                            title=clean_subject,
                            description=body,
                            customer_id=customer_id,
                            source="email",
                            priority="medium",
                            status="open",
                            email_thread_id=message_id,
                            requester_email=sender["email"],
                            requester_name=sender["name"] or sender["email"],
                            due_date=datetime.now(timezone.utc) + timedelta(hours=_SLA_HOURS["medium"]),
                        )
                        db.session.add(ticket)
                        db.session.commit()

                        try:
                            send_email_ticket_confirmation(
                                ticket.title, ticket.id, sender["email"],
                            )
                        except Exception:
                            pass

                        logger.info("Created ticket %s from email by %s", ticket.id, sender["email"])

                    mail.store(mid, "+FLAGS", "\\Seen")

                except Exception as exc:
                    logger.exception("Failed to process email message %s: %s", mid, exc)
                    db.session.rollback()

            mail.logout()

        except Exception as exc:
            logger.exception("poll_support_inbox failed")
            raise self.retry(exc=exc, countdown=120)
