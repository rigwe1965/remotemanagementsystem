"""Ticket Detail — full view with status, assignment, and comments."""
import streamlit as st
from datetime import datetime, timezone

from utils.auth import require_auth
from utils.nav import render_sidebar
from utils.styles import inject_css, badge, BRAND, section_header
from utils.formatters import fmt_datetime, PRIORITY_COLORS
from utils.sanitize import esc
from utils.ai_assistant import render_ai_assistant


def _sla_badge(ticket: dict) -> str:
    status = ticket.get("status", "open")
    if status in ("resolved", "closed"):
        return ""
    if ticket.get("sla_breached"):
        return '<span style="background:#DC2626;color:#fff;font-size:0.72rem;font-weight:700;padding:2px 8px;border-radius:999px">SLA BREACHED</span>'
    due = ticket.get("due_date")
    if not due:
        return ""
    try:
        due_dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
        diff = due_dt - datetime.now(timezone.utc)
        hours_left = diff.total_seconds() / 3600
        if hours_left < 0:
            return '<span style="background:#DC2626;color:#fff;font-size:0.72rem;font-weight:700;padding:2px 8px;border-radius:999px">SLA BREACHED</span>'
        elif hours_left < 2:
            return f'<span style="background:#F59E0B;color:#fff;font-size:0.72rem;font-weight:700;padding:2px 8px;border-radius:999px">Due {int(hours_left*60)}m</span>'
        elif hours_left < 24:
            return f'<span style="background:#D97706;color:#fff;font-size:0.72rem;font-weight:600;padding:2px 8px;border-radius:999px">Due {int(hours_left)}h</span>'
        else:
            days = int(hours_left / 24)
            return f'<span style="background:#6B7B6B;color:#fff;font-size:0.72rem;font-weight:600;padding:2px 8px;border-radius:999px">Due {days}d</span>'
    except Exception:
        return ""


STATUS_BADGE_COLORS = {
    "open":        BRAND["danger"],
    "in_progress": BRAND["warning"],
    "resolved":    BRAND["success"],
    "closed":      BRAND["muted"],
}

SOURCE_MAP = {
    "email":  ("EMAIL",  "#3B82F6"),
    "client": ("PORTAL", "#407E3C"),
    "alert":  ("ALERT",  "#EF4444"),
}

st.set_page_config(page_title="Ticket Detail — RMM", layout="wide")
inject_css()

client = require_auth()
render_sidebar()

me = st.session_state.get("user", {})
my_id = me.get("id")
my_role = me.get("role", "technician")
is_admin = my_role in ("admin", "superadmin")

# ── Back navigation ───────────────────────────────────────────────────────────
if st.button("← Back to Tickets", key="back_btn"):
    st.switch_page("pages/02_Tickets.py")

ticket_id = st.session_state.get("_nav_ticket_id")
if not ticket_id:
    st.error("No ticket selected. Use the Tickets list to open a ticket.")
    st.stop()

# ── Fetch ticket ──────────────────────────────────────────────────────────────
with st.spinner("Loading ticket…"):
    ticket, err = client.get_ticket(ticket_id)

if err or not ticket:
    st.error(f"Could not load ticket #{ticket_id}: {err or 'not found'}")
    st.stop()

priority_val  = ticket.get("priority", "medium")
status_val    = ticket.get("status", "open")
p_color       = PRIORITY_COLORS.get(priority_val, "#6B7B6B")
s_color       = STATUS_BADGE_COLORS.get(status_val, "#6B7B6B")
source_val    = ticket.get("source", "manual")
src_label, src_color = SOURCE_MAP.get(source_val, ("MANUAL", "#8492A6"))
customer_name = (
    ticket.get("customer_name")
    or (ticket.get("customer", {}).get("name", "—") if isinstance(ticket.get("customer"), dict) else "—")
)
requester_email = ticket.get("requester_email") or ""
created         = fmt_datetime(ticket.get("created_at", ""))
updated         = fmt_datetime(ticket.get("updated_at", ""))

# ── Ticket header ─────────────────────────────────────────────────────────────
st.markdown(
    f'<h2 style="margin:0.5rem 0 0.25rem">#{ticket_id} — {esc(ticket.get("title", "Untitled"))}</h2>',
    unsafe_allow_html=True,
)

badge_row = (
    badge(priority_val, p_color)
    + badge(status_val.replace("_", " "), s_color)
    + _sla_badge(ticket)
    + f'<span class="src" style="background:{src_color}20;color:{src_color};'
      f'display:inline-block;border-radius:10px;padding:2px 8px;font-size:0.68rem;font-weight:700">{src_label}</span>'
)

meta_parts = [f"<b>Customer:</b> {esc(customer_name)}"]
if requester_email:
    meta_parts.append(f"<b>Requester:</b> {esc(requester_email)}")
meta_parts.append(f"<b>Opened:</b> {created}")
if updated != created:
    meta_parts.append(f"<b>Updated:</b> {updated}")

st.markdown(
    f'<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:0.5rem">{badge_row}</div>'
    f'<div style="font-size:0.83rem;color:#6B7B6B;margin-bottom:1rem">'
    + " &nbsp;·&nbsp; ".join(meta_parts)
    + "</div>",
    unsafe_allow_html=True,
)

# ── Description ───────────────────────────────────────────────────────────────
desc_text = esc(ticket.get("description") or "No description provided.").replace("\n", "<br>")
st.markdown(
    '<div style="background:#F4F6F4;border-radius:8px;padding:0.85rem 1.1rem;'
    'border:1px solid #DDE8DD;margin-bottom:1.25rem;font-size:0.88rem;color:#1A1A1A;'
    'border-left:4px solid #407E3C">'
    + desc_text
    + "</div>",
    unsafe_allow_html=True,
)

TRIAGE_STATUS_LABELS = {
    "pending": "Queued for AI triage",
    "escalated": "Escalated to human review",
    "staged": "AI draft awaiting approval",
    "auto_resolved": "Auto-resolved by AI",
    "reopened": "Reopened after customer reply",
    "skipped": "AI triage skipped (rate-limited)",
    "error": "AI triage failed",
}

# ── Action tabs ───────────────────────────────────────────────────────────────
tab_names = ["Update Status", "Assignment", "Comments"]
if ticket.get("triage_status"):
    tab_names.append("AI Triage")
_tabs = st.tabs(tab_names)
tab_status, tab_assign, tab_comments = _tabs[0], _tabs[1], _tabs[2]
tab_triage = _tabs[3] if len(_tabs) > 3 else None

# Load user list once (needed for assignment tabs)
users_data, _ = client.list_users()
all_users = [
    u for u in (users_data.get("items", []) if isinstance(users_data, dict) else [])
    if u.get("is_active", True)
]

# ── Status tab ────────────────────────────────────────────────────────────────
with tab_status:
    st.markdown(section_header("Update Status"), unsafe_allow_html=True)
    statuses = ["open", "in_progress", "resolved", "closed"]
    cur_idx = statuses.index(status_val) if status_val in statuses else 0
    new_status = st.selectbox("Status", statuses, index=cur_idx, key="detail_status_sel")

    status_changing = new_status != status_val
    if status_changing:
        st.markdown(
            f'<div style="background:#FEF3C7;border:1px solid #D97706;border-radius:6px;'
            f'padding:0.4rem 0.75rem;font-size:0.82rem;color:#92400E;margin-bottom:0.5rem">'
            f'⚠ Changing status from <b>{status_val.replace("_", " ")}</b> to '
            f'<b>{new_status.replace("_", " ")}</b> — a comment is required.</div>',
            unsafe_allow_html=True,
        )
        status_comment = st.text_area(
            "Comment *",
            placeholder=(
                "Explain what was done, what changed, or what needs to happen next. "
                "This will be visible to the customer."
            ),
            height=100,
            key="detail_status_comment",
        )
    else:
        status_comment = ""

    if st.button("Update Status", key="detail_status_btn", type="primary"):
        if status_changing and not status_comment.strip():
            st.error("A comment is required before changing the ticket status.")
        else:
            payload = {"status": new_status}
            if status_changing:
                payload["status_comment"] = status_comment.strip()
            _, uerr = client.update_ticket(ticket_id, payload)
            if uerr:
                st.error(f"Update failed: {uerr}")
            else:
                st.success("Status updated." if not status_changing else "Status updated and comment posted.")
                st.rerun()

# ── Assignment tab ────────────────────────────────────────────────────────────
with tab_assign:
    st.markdown(section_header("Assignment"), unsafe_allow_html=True)
    cur_assignee = ticket.get("assignee_id")
    assigned_to_me = (cur_assignee == my_id)

    if is_admin:
        user_opts = {"— Unassigned —": None}
        user_opts.update({
            u.get("full_name") or u.get("email", u["id"]): u["id"]
            for u in all_users
        })
        cur_label = next((k for k, v in user_opts.items() if v == cur_assignee), "— Unassigned —")
        cur_idx2 = list(user_opts.keys()).index(cur_label) if cur_label in user_opts else 0
        new_assignee_label = st.selectbox(
            "Assignee", list(user_opts.keys()), index=cur_idx2, key="detail_assignee_sel",
        )
        a1, a2 = st.columns(2)
        with a1:
            if st.button("Assign", key="detail_assign_btn", width='stretch', type="primary"):
                new_uid = user_opts[new_assignee_label]
                _, aerr = client.update_ticket(ticket_id, {"assignee_id": new_uid})
                if aerr:
                    st.error(f"Assign failed: {aerr}")
                else:
                    st.success("Assigned.")
                    st.rerun()
        with a2:
            if st.button("Assign to Me", key="detail_assignme_btn", width='stretch'):
                _, aerr = client.update_ticket(ticket_id, {"assignee_id": my_id})
                if aerr:
                    st.error(f"Assign failed: {aerr}")
                else:
                    st.success("Assigned to you.")
                    st.rerun()
    else:
        if assigned_to_me:
            st.markdown(
                '<div style="background:#E8F5E8;border:1px solid #407E3C;border-radius:6px;'
                'padding:0.4rem 0.75rem;font-size:0.82rem;color:#407E3C;font-weight:600;'
                'margin-bottom:0.75rem">✓ Assigned to you</div>',
                unsafe_allow_html=True,
            )
        else:
            if st.button("Assign to Me", key="detail_assignme_tech", type="primary"):
                _, aerr = client.update_ticket(ticket_id, {"assignee_id": my_id})
                if aerr:
                    st.error(f"Assign failed: {aerr}")
                else:
                    st.success("Assigned to you.")
                    st.rerun()

        st.markdown(
            '<div style="font-size:0.78rem;color:#6B7B6B;margin-top:1rem;margin-bottom:0.3rem">'
            "Forward to</div>",
            unsafe_allow_html=True,
        )
        others = [u for u in all_users if u.get("id") != my_id]
        if others:
            fwd_opts = {u.get("full_name") or u.get("email", u["id"]): u["id"] for u in others}
            fwd_label = st.selectbox("Forward to", list(fwd_opts.keys()),
                                     key="detail_fwd_sel", label_visibility="collapsed")
            if st.button("Forward", key="detail_fwd_btn", width='stretch'):
                _, ferr = client.update_ticket(ticket_id, {"assignee_id": fwd_opts[fwd_label]})
                if ferr:
                    st.error(f"Forward failed: {ferr}")
                else:
                    st.success(f"Forwarded to {fwd_label}.")
                    st.rerun()
        else:
            st.caption("No other users to forward to.")

# ── Comments tab ──────────────────────────────────────────────────────────────
with tab_comments:
    comments = ticket.get("comments", [])

    if comments:
        st.markdown(
            '<div style="font-size:0.75rem;font-weight:700;text-transform:uppercase;'
            'letter-spacing:0.07em;color:#6B7B6B;margin-bottom:0.5rem">Thread</div>',
            unsafe_allow_html=True,
        )
        for c in comments:
            c_time = fmt_datetime(c.get("created_at", ""))
            is_internal = c.get("is_internal", False)
            border_color = "#D97706" if is_internal else "#407E3C"
            tag = (
                '<span style="background:#FEF3C7;color:#D97706;font-size:0.65rem;'
                'font-weight:700;padding:1px 6px;border-radius:10px;margin-left:6px">INTERNAL</span>'
                if is_internal else ""
            )
            author = c.get("author_name") or c.get("author_email") or "Staff"
            body_html = esc(c.get("body") or "").replace("\n", "<br>")
            st.markdown(
                f'<div style="background:#F9FBF9;border-left:3px solid {border_color};'
                f'padding:0.55rem 0.85rem;border-radius:0 6px 6px 0;margin-bottom:0.5rem">'
                f'<div style="font-size:0.78rem;color:#6B7B6B;margin-bottom:3px">'
                f'<b style="color:#1A1A1A">{esc(author)}</b>{tag} &nbsp;·&nbsp; {c_time}</div>'
                f'<div style="font-size:0.85rem;color:#1A1A1A">{body_html}</div>'
                f"</div>",
                unsafe_allow_html=True,
            )
    else:
        st.caption("No comments yet.")

    st.markdown(
        '<div style="font-size:0.75rem;font-weight:700;text-transform:uppercase;'
        'letter-spacing:0.07em;color:#6B7B6B;margin:1rem 0 0.4rem">Add Comment</div>',
        unsafe_allow_html=True,
    )
    with st.form("detail_comment_form", clear_on_submit=True):
        comment_body = st.text_area(
            "Comment", placeholder="Type your comment here…",
            height=90, label_visibility="collapsed",
        )
        cmt_c1, cmt_c2 = st.columns([1, 1])
        with cmt_c1:
            is_internal_new = st.checkbox("Internal note")
        with cmt_c2:
            cmt_submit = st.form_submit_button("Post Comment", width='stretch')

    if cmt_submit:
        if not comment_body.strip():
            st.warning("Comment cannot be empty.")
        else:
            _, cerr = client.add_comment(ticket_id, comment_body, is_internal=is_internal_new)
            if cerr:
                st.error(f"Failed to post comment: {cerr}")
            else:
                st.success("Comment posted.")
                st.rerun()

# ── AI Triage tab ─────────────────────────────────────────────────────────────
if tab_triage is not None:
    with tab_triage:
        st.markdown(section_header("AI Triage"), unsafe_allow_html=True)

        triage_status = ticket.get("triage_status")
        category = ticket.get("category") or ticket.get("ai_suggested_category")
        confidence = ticket.get("ai_confidence")

        status_label = TRIAGE_STATUS_LABELS.get(triage_status, triage_status or "—")
        conf_text = f"{confidence * 100:.0f}% confidence" if confidence is not None else "confidence n/a"
        st.markdown(
            f'<div style="display:flex;gap:8px;align-items:center;margin-bottom:0.75rem">'
            + badge(status_label, BRAND.get("accent", "#5a9e56"))
            + (badge(category, "#6B7B6B") if category else "")
            + f'<span style="font-size:0.78rem;color:#6B7B6B">{conf_text}</span>'
            + "</div>",
            unsafe_allow_html=True,
        )

        if ticket.get("ai_reasoning"):
            st.caption(f"AI reasoning (internal only): {esc(ticket['ai_reasoning'])}")

        if triage_status == "staged":
            st.markdown(
                '<div style="background:#FEF3C7;border:1px solid #D97706;border-radius:6px;'
                'padding:0.5rem 0.85rem;font-size:0.82rem;color:#92400E;margin-bottom:0.75rem">'
                'This category is in shadow mode — the AI drafted a reply below but will not send it '
                'or resolve the ticket until a technician approves it.</div>',
                unsafe_allow_html=True,
            )
            draft = st.text_area(
                "Draft reply (editable before sending)",
                value=ticket.get("ai_suggested_reply") or "",
                height=140, key="triage_draft_reply",
            )
            tc1, tc2 = st.columns(2)
            with tc1:
                if st.button("Approve & Send", key="triage_approve_btn", type="primary", width='stretch'):
                    override = draft if draft != (ticket.get("ai_suggested_reply") or "") else None
                    _, aerr = client.approve_triage(ticket_id, reply_override=override)
                    if aerr:
                        st.error(f"Approve failed: {aerr}")
                    else:
                        st.success("Reply sent and ticket resolved.")
                        st.rerun()
            with tc2:
                if st.button("Reject (escalate to me)", key="triage_reject_btn", width='stretch'):
                    _, rerr = client.reject_triage(ticket_id, assignee_id=my_id)
                    if rerr:
                        st.error(f"Reject failed: {rerr}")
                    else:
                        st.success("Escalated — assigned to you.")
                        st.rerun()
        elif triage_status == "auto_resolved":
            st.markdown(
                '<div style="font-size:0.75rem;font-weight:700;text-transform:uppercase;'
                'letter-spacing:0.07em;color:#6B7B6B;margin-bottom:0.4rem">Reply sent to customer</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div style="background:#F4F6F4;border-radius:8px;padding:0.75rem 1rem;'
                'border-left:3px solid #407E3C;font-size:0.85rem;color:#1A1A1A">'
                + esc(ticket.get("ai_suggested_reply") or "").replace("\n", "<br>")
                + "</div>",
                unsafe_allow_html=True,
            )
        elif triage_status == "escalated":
            st.caption("This ticket needs normal human handling — use the Update Status / Assignment tabs.")

render_ai_assistant("Tickets", {
    "ticket_id": ticket.get("id"), "title": ticket.get("title"),
    "status": ticket.get("status"), "priority": ticket.get("priority"),
})
