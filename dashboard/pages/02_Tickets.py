"""Tickets — Helpdesk ticket management (list view)."""
import streamlit as st
from datetime import datetime, timezone

from utils.auth import require_auth
from utils.nav import render_sidebar
from utils.ai_assistant import render_ai_assistant
from utils.styles import inject_css, badge, BRAND, STATUS_COLORS, section_header
from utils.formatters import fmt_datetime, PRIORITY_COLORS
from utils.sanitize import esc


def _sla_text(ticket: dict) -> tuple[str, str]:
    """Return (label, css_class) for SLA column in table."""
    status = ticket.get("status", "open")
    if status in ("resolved", "closed"):
        return ("—", "sla-ok")
    if ticket.get("sla_breached"):
        return ("BREACHED", "sla-breached")
    due = ticket.get("due_date")
    if not due:
        return ("—", "sla-ok")
    try:
        due_dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
        diff = due_dt - datetime.now(timezone.utc)
        hours_left = diff.total_seconds() / 3600
        if hours_left < 0:
            return ("BREACHED", "sla-breached")
        elif hours_left < 2:
            return (f"{int(hours_left * 60)}m", "sla-warn")
        elif hours_left < 24:
            return (f"{int(hours_left)}h", "sla-warn")
        else:
            return (f"{int(hours_left / 24)}d", "sla-ok")
    except Exception:
        return ("—", "sla-ok")


_TABLE_CSS = """
<style>
.bp{display:inline-block;border-radius:20px;padding:2px 9px;font-size:0.72rem;font-weight:700;white-space:nowrap;line-height:1.7}
.bp-critical{background:#FEE2E2;color:#DC2626}
.bp-high{background:#FEF3C7;color:#D97706}
.bp-medium{background:#DBEAFE;color:#2563EB}
.bp-low{background:#F3F4F6;color:#6B7B6B}
.bs{display:inline-block;border-radius:20px;padding:2px 9px;font-size:0.72rem;font-weight:700;white-space:nowrap;line-height:1.7}
.bs-open{background:#FEE2E2;color:#DC2626}
.bs-in_progress{background:#FEF3C7;color:#D97706}
.bs-resolved{background:#DCFCE7;color:#16A34A}
.bs-closed{background:#F3F4F6;color:#6B7B6B}
.src{display:inline-block;border-radius:10px;padding:2px 8px;font-size:0.68rem;font-weight:700;white-space:nowrap;line-height:1.7}
.triage-staged{background:#FEF3C7;color:#92400E}
.triage-auto{background:#DCFCE7;color:#166534}
.sla-breached{color:#DC2626;font-weight:700;font-size:0.78rem}
.sla-warn{color:#D97706;font-weight:700;font-size:0.78rem}
.sla-ok{color:#9CA3AF;font-size:0.78rem}
.tbl-sep{border:none;border-top:2px solid #407E3C;margin:4px 0 6px}
.tbl-row-sep{border:none;border-top:1px solid #EEF2EE;margin:2px 0}
</style>
"""

# Column widths for header + data rows (must match exactly)
_COL_W = [0.3, 0.55, 2.6, 1.0, 1.0, 1.5, 1.5, 0.8, 0.8, 0.95, 0.45]
_COL_HDR = ["", "#", "Title", "Priority", "Status", "Customer", "Assignee", "Source", "SLA", "Created", ""]
_SOURCE_MAP = {
    "email":  ("EMAIL",  "#3B82F6"),
    "client": ("PORTAL", "#407E3C"),
    "alert":  ("ALERT",  "#EF4444"),
}

st.set_page_config(page_title="Tickets — RMM", layout="wide")
inject_css()
st.markdown(_TABLE_CSS, unsafe_allow_html=True)

client = require_auth()
render_sidebar()

me = st.session_state.get("user", {})
my_id = me.get("id")
my_role = me.get("role", "technician")
is_admin = my_role in ("admin", "superadmin")

st.markdown(
    '<h1 style="margin:0">Tickets</h1>'
    '<p style="color:#6B7B6B;margin:2px 0 1rem;font-size:0.88rem">Helpdesk ticket management</p>',
    unsafe_allow_html=True,
)

# ── New Ticket form ───────────────────────────────────────────────────────────
with st.expander("+ New Ticket", expanded=False):
    cust_data, cust_err = client.list_customers(per_page=100)
    if cust_err:
        st.caption(f"⚠ Could not load customers — {cust_err}")
    customers = cust_data.get("items", []) if cust_data else []
    cust_options = {c["name"]: c["id"] for c in customers}
    cust_names = list(cust_options.keys()) if cust_options else ["— no customers —"]

    with st.form("create_ticket_form", clear_on_submit=True):
        st.markdown(
            '<div style="background:#FFFFFF;border-radius:12px;padding:1.2rem 1.5rem;'
            'border:1px solid #DDE8DD;box-shadow:0 2px 8px rgba(0,0,0,0.05);margin-bottom:1rem">'
            + section_header("Create New Ticket", "Fill in the details below")
            + "</div>",
            unsafe_allow_html=True,
        )
        fc1, fc2 = st.columns([2, 1])
        with fc1:
            new_title = st.text_input("Title *", placeholder="Brief description of the issue")
        with fc2:
            new_priority = st.selectbox("Priority", ["medium", "low", "high", "critical"])
        new_desc = st.text_area("Description", placeholder="Detailed description…", height=100)
        fc3, fc4 = st.columns([2, 1])
        with fc3:
            new_customer = st.selectbox("Customer *", cust_names)
        with fc4:
            st.write("")
            st.write("")
            submitted = st.form_submit_button("Create Ticket", width='stretch')

    if submitted:
        if not new_title or not cust_options:
            st.error("Title and a valid customer are required.")
        else:
            _, err = client.create_ticket({
                "title": new_title,
                "description": new_desc,
                "customer_id": cust_options[new_customer],
                "priority": new_priority,
            })
            if err:
                st.error(f"Failed to create ticket: {err}")
            else:
                st.success("Ticket created successfully!")
                st.rerun()


# ── Callbacks ─────────────────────────────────────────────────────────────────
def _on_select_all(tab_key: str, ticket_ids: list) -> None:
    checked = st.session_state.get(f"sel_all_{tab_key}", False)
    for tid in ticket_ids:
        st.session_state[f"sel_{tab_key}_{tid}"] = checked


def _clear_selection(tab_key: str, ticket_ids: list) -> None:
    for tid in ticket_ids:
        st.session_state[f"sel_{tab_key}_{tid}"] = False
    st.session_state[f"sel_all_{tab_key}"] = False


# ── Render function ───────────────────────────────────────────────────────────
def _render_tickets(tickets_list: list, tab_key: str) -> None:

    # Filter bar
    st.markdown(
        '<div style="background:#FFF;border-radius:10px;padding:0.9rem 1.1rem;'
        'border:1px solid #DDE8DD;margin-bottom:1rem">',
        unsafe_allow_html=True,
    )
    fb1, fb2, fb3 = st.columns([3, 1.5, 1.5])
    with fb1:
        search_q = st.text_input(
            "Search tickets", placeholder="Search by title or description…",
            label_visibility="collapsed", key=f"search_{tab_key}",
        )
    with fb2:
        priority_f = st.selectbox(
            "Priority", ["All", "critical", "high", "medium", "low"],
            label_visibility="collapsed", key=f"priority_{tab_key}",
        )
    with fb3:
        status_f = st.selectbox(
            "Status", ["All", "open", "in_progress", "resolved", "closed"],
            label_visibility="collapsed", key=f"status_{tab_key}",
        )
    st.markdown("</div>", unsafe_allow_html=True)

    # Client-side filtering
    tickets = tickets_list
    if search_q:
        q = search_q.lower()
        tickets = [t for t in tickets if q in t.get("title", "").lower()
                   or q in (t.get("description") or "").lower()]
    if priority_f != "All":
        tickets = [t for t in tickets if t.get("priority") == priority_f]
    if status_f != "All":
        tickets = [t for t in tickets if t.get("status") == status_f]

    ticket_ids = [t["id"] for t in tickets]

    # Count + Export
    cap_col, export_col = st.columns([6, 1])
    with cap_col:
        st.caption(f"Showing {len(tickets)} ticket{'s' if len(tickets) != 1 else ''}")
    with export_col:
        if tickets:
            import pandas as pd
            _df = pd.DataFrame([{
                "ID": t.get("id", ""), "Title": t.get("title", ""),
                "Status": t.get("status", ""), "Priority": t.get("priority", ""),
                "Customer": t.get("customer_name", ""), "Assignee": t.get("assignee_name", ""),
                "Created": t.get("created_at", ""), "Updated": t.get("updated_at", ""),
            } for t in tickets])
            st.download_button(
                "Export CSV", data=_df.to_csv(index=False).encode("utf-8"),
                file_name="tickets.csv", mime="text/csv",
                width='stretch', key=f"export_{tab_key}",
            )

    if not tickets:
        st.markdown(
            '<div style="background:#FFFFFF;border-radius:12px;padding:2.5rem 1.5rem;'
            'border:1px solid #DDE8DD;text-align:center;margin-top:1rem">'
            '<div style="font-size:0.95rem;font-weight:600;color:#6B7B6B">No tickets found</div>'
            '<div style="font-size:0.82rem;color:#9CA3AF;margin-top:0.25rem">'
            'Try adjusting your filters or create a new ticket above.</div>'
            "</div>",
            unsafe_allow_html=True,
        )
        return

    # Pre-compute selected IDs from previous render's session state
    selected_ids = [tid for tid in ticket_ids
                    if st.session_state.get(f"sel_{tab_key}_{tid}", False)]

    # ── Bulk action bar ───────────────────────────────────────────────────────
    if selected_ids:
        n = len(selected_ids)
        label_text = f"{n} ticket{'s' if n != 1 else ''} selected"

        st.markdown(
            f'<div style="background:#E8F5E8;border:1px solid #407E3C;border-radius:8px;'
            f'padding:0.45rem 1rem;margin-bottom:0.6rem;display:flex;align-items:center">'
            f'<span style="font-weight:700;color:#2D5C29;font-size:0.85rem">{label_text}</span>'
            f"</div>",
            unsafe_allow_html=True,
        )

        if is_admin:
            users_data_b, users_err_b = client.list_users()
            if users_err_b:
                st.caption(f"⚠ Could not load users — {users_err_b}")
            all_users_b = [
                u for u in (users_data_b.get("items", []) if isinstance(users_data_b, dict) else [])
                if u.get("is_active", True)
            ]
            user_opts_b = {
                u.get("full_name") or u.get("email", u["id"]): u["id"]
                for u in all_users_b
            }

            bb1, bb2, bb3, bb4, bb5, bb6 = st.columns([1.2, 1, 1.2, 1, 0.9, 0.8])
            with bb1:
                bulk_status = st.selectbox(
                    "Set status", ["open", "in_progress", "resolved", "closed"],
                    label_visibility="collapsed", key=f"bulk_status_{tab_key}",
                )
            with bb2:
                apply_status_clicked = st.button("Apply Status", key=f"bulk_apply_{tab_key}", width='stretch')
            with bb3:
                bulk_assign_lbl = st.selectbox(
                    "Assign to", list(user_opts_b.keys()),
                    label_visibility="collapsed", key=f"bulk_assign_lbl_{tab_key}",
                )
            with bb4:
                if st.button("Assign", key=f"bulk_assign_{tab_key}", width='stretch'):
                    uid = user_opts_b[bulk_assign_lbl]
                    for tid in selected_ids:
                        client.update_ticket(tid, {"assignee_id": uid})
                    _clear_selection(tab_key, ticket_ids)
                    st.success(f"Assigned {n} ticket{'s' if n != 1 else ''}.")
                    st.rerun()
            with bb5:
                close_all_clicked = st.button("Close All", key=f"bulk_close_{tab_key}", width='stretch', type="primary")
            with bb6:
                if st.button("Clear", key=f"bulk_clear_{tab_key}", width='stretch'):
                    _clear_selection(tab_key, ticket_ids)
                    st.rerun()

            if apply_status_clicked or close_all_clicked:
                target_status = "closed" if close_all_clicked else bulk_status
                bulk_comment = st.session_state.get(f"bulk_comment_{tab_key}", "").strip()
                if not bulk_comment:
                    st.session_state[f"bulk_needs_comment_{tab_key}"] = target_status
                else:
                    for tid in selected_ids:
                        client.update_ticket(tid, {"status": target_status, "status_comment": bulk_comment})
                    st.session_state.pop(f"bulk_needs_comment_{tab_key}", None)
                    st.session_state.pop(f"bulk_comment_{tab_key}", None)
                    _clear_selection(tab_key, ticket_ids)
                    action = "Closed" if target_status == "closed" else "Updated"
                    st.success(f"{action} {n} ticket{'s' if n != 1 else ''}.")
                    st.rerun()

            if st.session_state.get(f"bulk_needs_comment_{tab_key}"):
                target = st.session_state[f"bulk_needs_comment_{tab_key}"]
                st.warning(f"A comment is required to set status to **{target.replace('_', ' ')}**.")
                bulk_cmt = st.text_area(
                    "Reason for bulk status change *",
                    placeholder="Explain why all selected tickets are being updated…",
                    height=70,
                    key=f"bulk_comment_{tab_key}",
                )
                if st.button("Confirm & Apply", key=f"bulk_confirm_{tab_key}", type="primary"):
                    if not bulk_cmt.strip():
                        st.error("Comment cannot be empty.")
                    else:
                        for tid in selected_ids:
                            client.update_ticket(tid, {"status": target, "status_comment": bulk_cmt.strip()})
                        st.session_state.pop(f"bulk_needs_comment_{tab_key}", None)
                        _clear_selection(tab_key, ticket_ids)
                        st.success(f"Updated {n} ticket{'s' if n != 1 else ''}.")
                        st.rerun()
        else:
            # Technician bulk: self-assign + status change + clear
            tb1, tb2, tb3, tb4 = st.columns([1.2, 1, 1, 0.8])
            with tb1:
                bulk_status_t = st.selectbox(
                    "Set status", ["open", "in_progress", "resolved", "closed"],
                    label_visibility="collapsed", key=f"bulk_status_t_{tab_key}",
                )
            with tb2:
                apply_t_clicked = st.button("Apply Status", key=f"bulk_apply_t_{tab_key}", width='stretch')
            with tb3:
                if st.button("Assign to Me", key=f"bulk_me_{tab_key}", width='stretch'):
                    for tid in selected_ids:
                        client.update_ticket(tid, {"assignee_id": my_id})
                    _clear_selection(tab_key, ticket_ids)
                    st.success(f"Assigned {n} ticket{'s' if n != 1 else ''} to you.")
                    st.rerun()
            with tb4:
                if st.button("Clear", key=f"bulk_clear_t_{tab_key}", width='stretch'):
                    _clear_selection(tab_key, ticket_ids)
                    st.rerun()

            if apply_t_clicked:
                bulk_comment_t = st.session_state.get(f"bulk_comment_t_{tab_key}", "").strip()
                if not bulk_comment_t:
                    st.session_state[f"bulk_needs_comment_t_{tab_key}"] = bulk_status_t
                else:
                    for tid in selected_ids:
                        client.update_ticket(tid, {"status": bulk_status_t, "status_comment": bulk_comment_t})
                    st.session_state.pop(f"bulk_needs_comment_t_{tab_key}", None)
                    st.session_state.pop(f"bulk_comment_t_{tab_key}", None)
                    _clear_selection(tab_key, ticket_ids)
                    st.success(f"Updated {n} ticket{'s' if n != 1 else ''}.")
                    st.rerun()

            if st.session_state.get(f"bulk_needs_comment_t_{tab_key}"):
                target_t = st.session_state[f"bulk_needs_comment_t_{tab_key}"]
                st.warning(f"A comment is required to set status to **{target_t.replace('_', ' ')}**.")
                bulk_cmt_t = st.text_area(
                    "Reason for bulk status change *",
                    placeholder="Explain why all selected tickets are being updated…",
                    height=70,
                    key=f"bulk_comment_t_{tab_key}",
                )
                if st.button("Confirm & Apply", key=f"bulk_confirm_t_{tab_key}", type="primary"):
                    if not bulk_cmt_t.strip():
                        st.error("Comment cannot be empty.")
                    else:
                        for tid in selected_ids:
                            client.update_ticket(tid, {"status": bulk_status_t, "status_comment": bulk_cmt_t.strip()})
                        st.session_state.pop(f"bulk_needs_comment_t_{tab_key}", None)
                        _clear_selection(tab_key, ticket_ids)
                        st.success(f"Updated {n} ticket{'s' if n != 1 else ''}.")
                        st.rerun()

    # ── Table header row ──────────────────────────────────────────────────────
    hcols = st.columns(_COL_W)
    with hcols[0]:
        st.checkbox(
            "", key=f"sel_all_{tab_key}",
            label_visibility="collapsed",
            on_change=_on_select_all,
            args=(tab_key, ticket_ids),
        )
    for i, lbl in enumerate(_COL_HDR[1:], start=1):
        with hcols[i]:
            if lbl:
                st.markdown(
                    f'<span style="font-size:0.72rem;font-weight:700;text-transform:uppercase;'
                    f'letter-spacing:0.05em;color:#4B6349">{lbl}</span>',
                    unsafe_allow_html=True,
                )

    # Green separator under header
    st.markdown('<hr class="tbl-sep">', unsafe_allow_html=True)

    # ── Ticket rows ───────────────────────────────────────────────────────────
    for t in tickets:
        tid = t["id"]
        priority_val = t.get("priority", "medium")
        status_val = t.get("status", "open")
        customer_name = (
            t.get("customer_name")
            or (t.get("customer", {}).get("name", "—") if isinstance(t.get("customer"), dict) else "—")
        )
        assignee_name = t.get("assignee_name") or "—"
        source_val = t.get("source", "manual")
        src_label, src_color = _SOURCE_MAP.get(source_val, ("MANUAL", "#8492A6"))
        created_short = fmt_datetime(t.get("created_at", ""))
        sla_label, sla_cls = _sla_text(t)
        status_display = status_val.replace("_", " ").upper()

        rcols = st.columns(_COL_W)
        with rcols[0]:
            st.checkbox("", key=f"sel_{tab_key}_{tid}", label_visibility="collapsed")
        with rcols[1]:
            st.markdown(
                f'<span style="font-size:0.8rem;color:#6B7B6B;font-weight:600">#{str(tid)[:8]}</span>',
                unsafe_allow_html=True,
            )
        with rcols[2]:
            triage_status = t.get("triage_status")
            triage_chip = ""
            if triage_status == "staged":
                triage_chip = ' <span class="src triage-staged">AI DRAFT — NEEDS APPROVAL</span>'
            elif triage_status == "auto_resolved":
                triage_chip = ' <span class="src triage-auto">AI RESOLVED</span>'
            st.markdown(
                f'<span style="font-size:0.84rem;color:#1A1A1A;font-weight:500">'
                f'{esc(t.get("title", "Untitled"))}</span>{triage_chip}',
                unsafe_allow_html=True,
            )
        with rcols[3]:
            st.markdown(
                f'<span class="bp bp-{priority_val}">{priority_val.upper()}</span>',
                unsafe_allow_html=True,
            )
        with rcols[4]:
            st.markdown(
                f'<span class="bs bs-{status_val}">{status_display}</span>',
                unsafe_allow_html=True,
            )
        with rcols[5]:
            st.markdown(
                f'<span style="font-size:0.83rem;color:#1A1A1A">{esc(customer_name)}</span>',
                unsafe_allow_html=True,
            )
        with rcols[6]:
            st.markdown(
                f'<span style="font-size:0.83rem;color:#6B7B6B">{esc(assignee_name)}</span>',
                unsafe_allow_html=True,
            )
        with rcols[7]:
            st.markdown(
                f'<span class="src" style="background:{src_color}20;color:{src_color}">{src_label}</span>',
                unsafe_allow_html=True,
            )
        with rcols[8]:
            st.markdown(
                f'<span class="{sla_cls}">{sla_label}</span>',
                unsafe_allow_html=True,
            )
        with rcols[9]:
            st.markdown(
                f'<span style="font-size:0.78rem;color:#9CA3AF">{created_short}</span>',
                unsafe_allow_html=True,
            )
        with rcols[10]:
            if st.button("→", key=f"view_{tab_key}_{tid}", width='stretch'):
                st.session_state["_nav_ticket_id"] = tid
                st.switch_page("pages/_ticket_detail.py")

        st.markdown('<hr class="tbl-row-sep">', unsafe_allow_html=True)


# ── Load and render per tab ───────────────────────────────────────────────────
tab_all, tab_mine, tab_unassigned = st.tabs(["All Tickets", "My Tickets", "Unassigned"])

with tab_all:
    with st.spinner("Loading tickets…"):
        data, err = client.list_tickets()
    if err:
        st.warning(f"Could not load tickets — {err}")
    else:
        _render_tickets(data.get("items", []) if data else [], "all")

with tab_mine:
    with st.spinner("Loading your tickets…"):
        data_mine, err_mine = client.list_tickets(assignee_id=my_id)
    if err_mine:
        st.warning(f"Could not load tickets — {err_mine}")
    else:
        _render_tickets(data_mine.get("items", []) if data_mine else [], "mine")

with tab_unassigned:
    with st.spinner("Loading unassigned tickets…"):
        data_all, err_all = client.list_tickets()
    if err_all:
        st.warning(f"Could not load tickets — {err_all}")
    else:
        all_items = data_all.get("items", []) if data_all else []
        unassigned = [t for t in all_items if not t.get("assignee_id")]
        _render_tickets(unassigned, "unassigned")

_ai_tlist = data.get("items", []) if (data and not err) else []
render_ai_assistant("Tickets", {
    "total_tickets": len(_ai_tlist),
    "open_or_in_progress": sum(1 for t in _ai_tlist if t.get("status") in ("open", "in_progress")),
    "sla_breached": sum(1 for t in _ai_tlist if t.get("sla_breached")),
})
