"""AI ticket triage — categorize every new ticket and, for a curated whitelist of
categories proven accurate in shadow mode, let the AI reply to the customer and
resolve the ticket itself. Everything else escalates to a human with the AI's
suggested category and a drafted reply attached.

Safety model (see CLAUDE.md / plan doc for full rationale):
  - The model returns a structured forced tool call (category/confidence/draft_reply/
    reasoning) — never free text parsed for intent. A numeric confidence field is a
    code-level gate; prose hedging is not.
  - The actual auto-resolve decision is computed server-side from the TriageCategory
    DB row (auto_resolve_enabled + shadow_mode + confidence_threshold), fetched fresh
    in the same transaction. The model's own `is_auto_resolvable` opinion is logged
    for later accuracy evaluation but never drives the branch.
  - Every outbound AI-drafted reply is re-scanned with the same danger-pattern list
    the AI assistant uses before it can ever be staged or sent; a hit forces escalation
    regardless of category/confidence.
"""
import os
import time
import logging
from datetime import datetime, timezone

from extensions import db
from models.ticket import Ticket
from models.triage_category import TriageCategory
from models.audit import AuditLog
from services.ai_prompt import _DANGER_PATTERNS
from utils.ai_client import get_anthropic_client, get_model
from utils.rate_limit import check_and_increment
from utils.usage_tracker import record_event

logger = logging.getLogger(__name__)

_CATEGORIZE_TOOL = {
    "name": "categorize_ticket",
    "description": "Categorize this support ticket and, if it is a common, low-risk issue you can "
                   "confidently resolve from the information given, draft a customer-facing reply.",
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "The single best-fit category code from the list provided, or 'other' "
                               "if none confidently apply.",
            },
            "confidence": {
                "type": "number",
                "description": "Your confidence in this category assignment, 0.0 to 1.0.",
            },
            "is_auto_resolvable": {
                "type": "boolean",
                "description": "Your own opinion on whether draft_reply fully resolves the customer's "
                               "issue without a human needing to act. This is advisory only — the system "
                               "decides independently whether to actually send it.",
            },
            "draft_reply": {
                "type": "string",
                "description": "A customer-facing reply addressing the ticket. Plain language, no "
                               "internal jargon. Write this even if you are not confident it is fully "
                               "resolvable — it may be used as a starting draft for a human.",
            },
            "reasoning": {
                "type": "string",
                "description": "Brief internal-only justification for the category and confidence. "
                               "Never shown to the customer.",
            },
        },
        "required": ["category", "confidence", "is_auto_resolvable", "draft_reply", "reasoning"],
    },
}


def _active_categories() -> list:
    return TriageCategory.query.filter_by(is_active=True).order_by(TriageCategory.code).all()


def build_triage_prompt(ticket: Ticket) -> tuple:
    categories = _active_categories()
    cat_lines = "\n".join(f"- {c.code}: {c.label} — {c.description or ''}" for c in categories)
    cat_lines += "\n- other: None of the above confidently apply"

    device_line = ""
    if ticket.device_id:
        try:
            from models.device import Device
            device = db.session.get(Device, ticket.device_id)
            if device:
                device_line = (
                    f"\nRelated device: {device.hostname} ({device.platform or 'unknown platform'}, "
                    f"status: {device.status or 'unknown'})"
                )
        except Exception:
            pass

    customer_name = "Unknown"
    try:
        from models.customer import Customer
        cust = db.session.get(Customer, ticket.customer_id)
        if cust:
            customer_name = cust.name
    except Exception:
        pass

    description = (ticket.description or "")[:3000]

    system_prompt = f"""You are the ticket triage assistant for a Remote Monitoring & Management (RMM) platform. Your job is to categorize this support ticket and, if it is clearly a common, low-risk issue, draft a helpful customer-facing reply.

AVAILABLE CATEGORIES:
{cat_lines}

Call categorize_ticket exactly once. Be conservative with confidence — only use high confidence (>0.85) when the category is unambiguous from the ticket text. If the ticket requires looking at live device state, running a script, or any action beyond giving information, set is_auto_resolvable to false even if the category is clear."""

    user_content = (
        f"Ticket title: {ticket.title}\n"
        f"Customer: {customer_name}\n"
        f"Priority: {ticket.priority}\n"
        f"Source: {ticket.source}"
        f"{device_line}\n\n"
        f"Description:\n{description or '(no description provided)'}"
    )

    return system_prompt, user_content


def danger_scan(text: str) -> bool:
    """Reused by routes/ticket_triage.py to re-scan a human-edited reply_override
    before it's sent on approval."""
    if not text:
        return False
    return any(p.search(text) for p in _DANGER_PATTERNS)


def apply_triage_decision(ticket: Ticket, *, category: str, confidence: float,
                          is_auto_resolvable: bool, draft_reply: str, reasoning: str, model: str):
    """Server-side gate — see module docstring. Commits the ticket and writes the
    AuditLog row; caller (run_triage) handles the outbound notification."""
    from services.ticket_service import update_ticket_service

    ticket.ai_suggested_category = category
    ticket.ai_confidence = confidence
    ticket.ai_suggested_reply = draft_reply
    ticket.ai_reasoning = reasoning
    ticket.triage_model = model
    ticket.triaged_at = datetime.now(timezone.utc)

    cat_row = TriageCategory.query.filter_by(code=category, is_active=True).first() if category != "other" else None
    danger_hit = danger_scan(draft_reply)

    eligible = (
        cat_row is not None
        and cat_row.auto_resolve_enabled
        and confidence >= cat_row.confidence_threshold
        and not danger_hit
    )

    if not eligible:
        ticket.category = category
        ticket.triage_status = "escalated"
        db.session.add(AuditLog(
            action="AI_TRIAGE_ESCALATED", resource_type="ticket", resource_id=ticket.id,
            payload={
                "category": category, "confidence": confidence, "model": model,
                "reason": "danger_pattern" if danger_hit else ("not_whitelisted" if not cat_row else "low_confidence"),
            },
        ))
        db.session.commit()
        try:
            from utils.notifications import send_ticket_escalated_notification
            send_ticket_escalated_notification(ticket, reason="New ticket triaged — needs human review")
        except Exception:
            logger.warning("Escalation notification failed for ticket %s", ticket.id, exc_info=True)
        return "escalated"

    if cat_row.shadow_mode:
        ticket.category = category
        ticket.triage_status = "staged"
        db.session.add(AuditLog(
            action="AI_TRIAGE_STAGED", resource_type="ticket", resource_id=ticket.id,
            payload={"category": category, "confidence": confidence, "model": model},
        ))
        db.session.commit()
        return "staged"

    # Fully automatic — whitelisted, shadow mode off, confidence passed, reply is clean.
    ticket.category = category
    update_ticket_service(
        None, "system", ticket,
        status="resolved", status_comment="Auto-resolved by AI triage.",
        skip_status_comment_requirement=True,
    )
    ticket.auto_resolved = True
    ticket.triage_status = "auto_resolved"
    db.session.add(AuditLog(
        action="AI_TRIAGE_AUTO_RESOLVED", resource_type="ticket", resource_id=ticket.id,
        payload={"category": category, "confidence": confidence, "model": model},
    ))
    db.session.commit()

    try:
        from utils.notifications import send_ai_ticket_resolution
        auto_close_days = cat_row.auto_close_days or int(os.getenv("AI_TRIAGE_AUTO_CLOSE_DAYS", "7"))
        send_ai_ticket_resolution(
            ticket.title, ticket.id, draft_reply,
            [], ticket.requester_email, auto_close_days,
        )
    except Exception:
        logger.warning("AI resolution email failed for ticket %s", ticket.id, exc_info=True)

    return "auto_resolved"


def run_triage(ticket_id: str):
    """Called by tasks/triage_tasks.py::triage_ticket inside an app context.
    Idempotency and retry are the caller's responsibility."""
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket:
        return

    allowed = check_and_increment(
        "rmm:ai:triage:hourly",
        int(os.getenv("AI_TRIAGE_RATE_LIMIT_PER_HOUR", "300")),
        3600,
    )
    if not allowed:
        ticket.triage_status = "skipped"
        ticket.ai_reasoning = "Rate limit exceeded"
        ticket.triaged_at = datetime.now(timezone.utc)
        db.session.commit()
        try:
            from utils.notifications import send_ticket_escalated_notification
            send_ticket_escalated_notification(ticket, reason="AI triage rate-limited — needs human review")
        except Exception:
            pass
        return

    system_prompt, user_content = build_triage_prompt(ticket)
    model = get_model("AI_TRIAGE_MODEL", get_model("AI_ASSISTANT_MODEL", "claude-haiku-4-5-20251001"))
    max_tokens = int(os.getenv("AI_TRIAGE_MAX_TOKENS", "500"))

    _t0 = time.perf_counter()
    try:
        client = get_anthropic_client()
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
            tools=[_CATEGORIZE_TOOL],
            tool_choice={"type": "tool", "name": "categorize_ticket"},
        )
        _usage = getattr(resp, "usage", None)
        tool_block = next((b for b in resp.content if getattr(b, "type", None) == "tool_use"), None)
        if not tool_block:
            raise RuntimeError("Model did not return the forced categorize_ticket tool call")
        result = tool_block.input or {}

        record_event(
            service="ai_ticket_triage", feature=result.get("category", "uncategorized"),
            input_tokens=getattr(_usage, "input_tokens", None) if _usage else None,
            output_tokens=getattr(_usage, "output_tokens", None) if _usage else None,
            status="success", latency_ms=int((time.perf_counter() - _t0) * 1000), model=model,
        )

        apply_triage_decision(
            ticket,
            category=str(result.get("category", "other"))[:50],
            confidence=float(result.get("confidence", 0) or 0),
            is_auto_resolvable=bool(result.get("is_auto_resolvable", False)),
            draft_reply=str(result.get("draft_reply", ""))[:5000],
            reasoning=str(result.get("reasoning", ""))[:2000],
            model=model,
        )
    except Exception as exc:
        record_event(service="ai_ticket_triage", feature="error", status="error",
                     latency_ms=int((time.perf_counter() - _t0) * 1000), error=type(exc).__name__, model=model)
        logger.exception("run_triage failed for ticket %s", ticket_id)
        raise
