import os
import streamlit as st
from utils.styles import inject_css, badge, BRAND, STATUS_COLORS
from utils.formatters import fmt_datetime, SUPPORTED_CURRENCIES, SUPPORTED_TIMEZONES
from utils.auth import require_auth, current_user
from utils.nav import render_sidebar
from utils.ai_assistant import render_ai_assistant
from utils.sanitize import esc

st.set_page_config(page_title="Admin — RMM", layout="wide")
inject_css()

client = require_auth()
render_sidebar()
user = current_user() or {}

# ── Role guard ─────────────────────────────────────────────────────────────────
if user.get("role") not in ("admin", "superadmin"):
    st.error("Admin access required. This page is restricted to admin users.")
    from utils.auth import logout
    if st.button("Sign Out / Switch Account", type="primary"):
        logout()
    st.stop()

# ── Page header ────────────────────────────────────────────────────────────────
st.markdown('<h1 style="margin:0">Admin</h1><p style="color:#6B7B6B;margin:2px 0 1rem;font-size:0.88rem">System administration and audit</p>', unsafe_allow_html=True)

CARD = (
    "background:#FFFFFF;border-radius:12px;padding:1.2rem 1.5rem;"
    "border:1px solid #DDE8DD;box-shadow:0 2px 8px rgba(0,0,0,0.05);margin-bottom:1rem"
)

ACTION_COLORS = {
    "CREATE": "#22C55E",
    "UPDATE": "#3B82F6",
    "DELETE": "#EF4444",
    "LOGIN":  "#8B5CF6",
    "LOGOUT": "#F59E0B",
}

API_URL = os.getenv("API_BASE_URL", "http://localhost:5000")
DASH_URL = "http://localhost:8501"

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab_sysinfo, tab_audit, tab_users, tab_depts, tab_org, tab_triage = st.tabs(
    ["System Info", "Audit Log", "Users", "Departments", "Org Settings", "AI Triage"]
)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — System Info
# ═══════════════════════════════════════════════════════════════════════════════
with tab_sysinfo:
    st.markdown("<div style='height:0.25rem'></div>", unsafe_allow_html=True)

    col_user, col_system, col_services = st.columns(3)

    with col_user:
        st.markdown(
            f'<div style="{CARD}">'
            f'<div style="font-size:0.72rem;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;color:#6B7B6B;margin-bottom:0.75rem">Current User</div>'
            f'<div style="font-size:1.1rem;font-weight:700;color:#1A1A1A;margin-bottom:0.25rem">{esc(user.get("full_name") or user.get("email","—"))}</div>'
            f'<div style="margin-bottom:0.5rem">'
            + badge(user.get("role","unknown"), "#407E3C")
            + f'</div>'
            f'<div style="display:flex;gap:6px;margin-bottom:0.3rem"><span style="font-size:0.8rem;color:#6B7B6B;min-width:48px">Email</span><span style="font-size:0.8rem;color:#1A1A1A">{esc(user.get("email","—"))}</span></div>'
            f'<div style="display:flex;gap:6px"><span style="font-size:0.8rem;color:#6B7B6B;min-width:48px">Role</span><span style="font-size:0.8rem;color:#1A1A1A;text-transform:capitalize">{user.get("role","—")}</span></div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    with col_system:
        support_email = os.getenv("SUPPORT_IMAP_USER", "")
        support_configured = bool(support_email and os.getenv("SUPPORT_IMAP_HOST", ""))
        support_line = (
            f'<div style="display:flex;gap:6px;margin-top:0.5rem"><span style="font-size:0.8rem;color:#6B7B6B;min-width:72px">Support</span>'
            f'<span style="font-size:0.8rem;color:#407E3C;font-family:monospace">{support_email}</span></div>'
            if support_configured else
            f'<div style="display:flex;gap:6px;margin-top:0.5rem"><span style="font-size:0.8rem;color:#6B7B6B;min-width:72px">Support</span>'
            f'<span style="font-size:0.8rem;color:#8492A6">not configured</span></div>'
        )
        st.markdown(
            f'<div style="{CARD}">'
            f'<div style="font-size:0.72rem;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;color:#6B7B6B;margin-bottom:0.75rem">System</div>'
            f'<div style="display:flex;gap:6px;margin-bottom:0.5rem"><span style="font-size:0.8rem;color:#6B7B6B;min-width:72px">API URL</span>'
            f'<span style="font-size:0.8rem;color:#407E3C;font-family:monospace;word-break:break-all">{API_URL}</span></div>'
            f'<div style="display:flex;gap:6px;margin-bottom:0.5rem"><span style="font-size:0.8rem;color:#6B7B6B;min-width:72px">Dashboard</span>'
            f'<span style="font-size:0.8rem;color:#407E3C;font-family:monospace;word-break:break-all">{DASH_URL}</span></div>'
            f'<div style="display:flex;gap:6px"><span style="font-size:0.8rem;color:#6B7B6B;min-width:72px">DB</span>'
            f'<span style="font-size:0.8rem;color:#1A1A1A;font-family:monospace">localhost:5432 / rmmdb</span></div>'
            + support_line +
            f'</div>',
            unsafe_allow_html=True,
        )

    with col_services:
        # Probe API health
        health_data, health_err = client._get("/api/health") if hasattr(client, "_get") else (None, "n/a")
        api_ok = health_err is None and health_data is not None
        api_dot = "#22C55E" if api_ok else "#EF4444"
        api_label = "Online" if api_ok else "Unreachable"

        st.markdown(
            f'<div style="{CARD}">'
            f'<div style="font-size:0.72rem;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;color:#6B7B6B;margin-bottom:0.75rem">Services</div>'
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:0.55rem">'
            f'<div style="width:8px;height:8px;border-radius:50%;background:{api_dot};flex-shrink:0"></div>'
            f'<span style="font-size:0.82rem;color:#1A1A1A;font-weight:500">Flask API</span>'
            f'<span style="font-size:0.75rem;color:{api_dot};margin-left:auto">{api_label}</span></div>'
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:0.55rem">'
            f'<div style="width:8px;height:8px;border-radius:50%;background:#22C55E;flex-shrink:0"></div>'
            f'<span style="font-size:0.82rem;color:#1A1A1A;font-weight:500">Streamlit Dashboard</span>'
            f'<span style="font-size:0.75rem;color:#22C55E;margin-left:auto">Running</span></div>'
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:0.55rem">'
            f'<div style="width:8px;height:8px;border-radius:50%;background:#F59E0B;flex-shrink:0"></div>'
            f'<span style="font-size:0.82rem;color:#1A1A1A;font-weight:500">PostgreSQL</span>'
            f'<span style="font-size:0.75rem;color:#F59E0B;margin-left:auto">localhost:5432</span></div>'
            f'<div style="display:flex;align-items:center;gap:8px">'
            f'<div style="width:8px;height:8px;border-radius:50%;background:#F59E0B;flex-shrink:0"></div>'
            f'<span style="font-size:0.82rem;color:#1A1A1A;font-weight:500">Redis / Celery</span>'
            f'<span style="font-size:0.75rem;color:#F59E0B;margin-left:auto">localhost:6379</span></div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── Agent Enrollment Token + Server IPs (fetched in parallel) ───────────────
    st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

    from concurrent.futures import ThreadPoolExecutor as _TPE
    with _TPE(max_workers=2) as _ex:
        _fo = _ex.submit(client.get_org_token)
        _fi = _ex.submit(client.get_server_ips)
        org_data, org_err = _fo.result()
        ip_data, ip_err = _fi.result()

    org_token_val = org_data.get("org_token", "") if org_data else ""

    masked = org_token_val[:6] + "•" * (len(org_token_val) - 6) if len(org_token_val) > 6 else "••••••••"
    show_key = "admin_show_org_token"
    if show_key not in st.session_state:
        st.session_state[show_key] = False

    st.markdown(
        f'<div style="{CARD}">'
        f'<div style="font-size:0.72rem;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.08em;color:#6B7B6B;margin-bottom:0.75rem">Agent Enrollment Token</div>'
        f'<div style="font-size:0.8rem;color:#4B5B4B;margin-bottom:0.75rem">'
        f'Paste this token into <code>config.ini → org_token</code> on any machine you want to enroll. '
        f'Keep it secret — anyone with this token can register devices to your org.</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Server IP / Agent Setup ───────────────────────────────────────────────
    st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)
    lan_ips = (ip_data or {}).get("lan_ips", [])
    server_hostname = (ip_data or {}).get("hostname", "—")

    st.markdown(
        f'<div style="{CARD}">'
        f'<div style="font-size:0.72rem;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.08em;color:#6B7B6B;margin-bottom:0.75rem">WiFi / LAN Agent Setup</div>'
        f'<div style="font-size:0.8rem;color:#4B5B4B;margin-bottom:0.75rem">'
        f'Server hostname: <b>{server_hostname}</b>. Copy an IP below, '
        f'then use it as the <code>url</code> in <code>agent/config.ini</code> '
        f'on any device you want to enroll over WiFi or LAN.</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    if ip_err:
        st.warning(f"Could not detect server IPs: {ip_err}")
    elif lan_ips:
        for ip in lan_ips:
            st.code(f"http://{ip}:5000", language=None)
    else:
        st.info("No LAN IPs detected. Make sure the server is connected to the network.")

    with st.expander("Agent setup instructions"):
        st.markdown("""
**To enroll a WiFi/LAN laptop or desktop:**

1. Copy the `agent/` folder to the target machine (USB, shared drive, or `scp`).
2. Edit `agent/config.ini`:
   ```ini
   [api]
   url = http://<SERVER_IP_FROM_ABOVE>:5000
   org_token = <paste enrollment token below>
   ```
   *(Delete the `[agent]` section entirely if re-registering an existing machine.)*
3. On the target machine, run:
   ```
   python setup_agent.py <SERVER_IP> <ORG_TOKEN>
   ```
   Or manually edit `config.ini` and run:
   ```
   python rmm_agent.py
   ```
4. The device appears in the **Devices** page within 60 seconds.

**For mobile phones / tablets:** Use **Network Discovery** to scan your subnet — phones are auto-detected via MAC/OUI and ping-monitored. No agent needed.
""")

    st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

    if org_err:
        st.warning(f"Could not load org token: {org_err}")
    elif org_token_val:
        tok_col, btn_col, copy_col = st.columns([6, 1, 1])
        with tok_col:
            display_val = org_token_val if st.session_state[show_key] else masked
            st.code(display_val, language=None)
        with btn_col:
            label = "Hide" if st.session_state[show_key] else "Reveal"
            if st.button(label, key="toggle_org_token", width='stretch'):
                st.session_state[show_key] = not st.session_state[show_key]
                st.rerun()
        with copy_col:
            st.button("Copy", key="copy_org_token", width='stretch',
                      help="Click Reveal first, then copy from the code block above.")

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Audit Log
# ═══════════════════════════════════════════════════════════════════════════════
with tab_audit:
    st.markdown("<div style='height:0.25rem'></div>", unsafe_allow_html=True)

    # ── Filters ──
    f1, f2, f3 = st.columns([2, 2, 3])
    with f1:
        action_filter = st.selectbox(
            "Action type",
            ["All", "CREATE", "UPDATE", "DELETE", "LOGIN", "LOGOUT"],
            label_visibility="visible",
        )
    with f2:
        date_from = st.date_input("From date", value=None, label_visibility="visible")
    with f3:
        date_to = st.date_input("To date", value=None, label_visibility="visible")

    st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

    feed, ferr = client.get_activity_feed()
    if ferr:
        st.error(f"API error: {ferr}")
    elif not feed:
        st.markdown(
            f'<div style="{CARD};text-align:center;padding:2.5rem 1.5rem">'
            f'<div style="font-size:1.8rem;margin-bottom:0.5rem"><i class="fa-solid fa-pen-to-square" style="color:#6B7B6B"></i></div>'
            f'<div style="font-size:0.95rem;font-weight:600;color:#1A1A1A">No audit events yet</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        # Apply filters client-side
        items = feed if isinstance(feed, list) else feed.get("items", [])

        if action_filter != "All":
            items = [i for i in items if (i.get("action") or "").upper() == action_filter]
        if date_from:
            items = [i for i in items if i.get("created_at", "") >= str(date_from)]
        if date_to:
            items = [i for i in items if i.get("created_at", "") <= str(date_to) + "T23:59:59"]

        cnt_col, exp_col = st.columns([5, 1])
        with cnt_col:
            st.markdown(
                f'<div style="font-size:0.8rem;color:#6B7B6B;margin-bottom:0.6rem"><b>{len(items)}</b> events</div>',
                unsafe_allow_html=True,
            )
        with exp_col:
            import pandas as pd
            _audit_df = pd.DataFrame([{
                "Timestamp": i.get("created_at", ""),
                "User": i.get("user_email", ""),
                "Action": (i.get("action") or "").upper(),
                "Resource": i.get("resource_type", ""),
                "Resource ID": i.get("resource_id", ""),
                "IP": i.get("ip_address", ""),
            } for i in items])
            st.download_button(
                "Export CSV",
                data=_audit_df.to_csv(index=False).encode("utf-8"),
                file_name="audit_log.csv", mime="text/csv",
                width='stretch',
            )

        # ── Render as HTML table for performance ──
        rows_html = ""
        for item in items:
            action = (item.get("action") or "—").upper()
            resource_type = item.get("resource_type") or "—"
            resource_id = item.get("resource_id") or ""
            ts = fmt_datetime(item.get("created_at", ""))
            ip = item.get("ip_address") or "—"
            user_email     = item.get("user_email") or ""
            user_full_name = item.get("user_full_name") or ""
            # Build user cell: "Full Name\nemail" or just email/dash
            if user_full_name and user_full_name != "—":
                user_cell = (
                    f'<span style="font-weight:600;color:#1A1A1A">{esc(user_full_name)}</span>'
                    f'<br><span style="color:#6B7B6B;font-size:0.73rem">{esc(user_email)}</span>'
                )
            elif user_email and user_email != "—":
                user_cell = f'<span style="color:#1A1A1A">{esc(user_email)}</span>'
            else:
                user_cell = '<span style="color:#6B7B6B">—</span>'
            color = ACTION_COLORS.get(action, "#6B7B6B")
            resource_display = esc(f"{resource_type}:{resource_id}" if resource_id else resource_type)
            rows_html = (rows_html
                + f'<tr>'
                + f'<td style="padding:0.5rem 0.75rem;white-space:nowrap"><span style="background:{color}1A;color:{color};padding:2px 9px;border-radius:5px;font-size:0.7rem;font-weight:700;border:1px solid {color}33">{action}</span></td>'
                + f'<td style="padding:0.5rem 0.75rem;font-size:0.82rem;color:#1A1A1A;font-weight:500">{resource_display}</td>'
                + f'<td style="padding:0.5rem 0.75rem;font-size:0.78rem;color:#6B7B6B;white-space:nowrap">{ts}</td>'
                + f'<td style="padding:0.5rem 0.75rem;font-size:0.78rem;color:#6B7B6B;font-family:monospace">{esc(ip)}</td>'
                + f'<td style="padding:0.5rem 0.75rem;font-size:0.82rem;line-height:1.4">{user_cell}</td>'
                + f'</tr>'
            )

        table_html = (
            f'<div style="{CARD};padding:0;overflow:hidden">'
            f'<table style="width:100%;border-collapse:collapse">'
            f'<thead><tr style="border-bottom:1px solid #DDE8DD;background:#FAFCFA">'
            f'<th style="padding:0.6rem 0.75rem;text-align:left;font-size:0.7rem;font-weight:700;text-transform:uppercase;letter-spacing:0.07em;color:#6B7B6B;white-space:nowrap">Action</th>'
            f'<th style="padding:0.6rem 0.75rem;text-align:left;font-size:0.7rem;font-weight:700;text-transform:uppercase;letter-spacing:0.07em;color:#6B7B6B">Resource</th>'
            f'<th style="padding:0.6rem 0.75rem;text-align:left;font-size:0.7rem;font-weight:700;text-transform:uppercase;letter-spacing:0.07em;color:#6B7B6B;white-space:nowrap">Timestamp</th>'
            f'<th style="padding:0.6rem 0.75rem;text-align:left;font-size:0.7rem;font-weight:700;text-transform:uppercase;letter-spacing:0.07em;color:#6B7B6B">IP Address</th>'
            f'<th style="padding:0.6rem 0.75rem;text-align:left;font-size:0.7rem;font-weight:700;text-transform:uppercase;letter-spacing:0.07em;color:#6B7B6B">User</th>'
            f'</tr></thead>'
            f'<tbody>'
            + rows_html
            + f'</tbody></table></div>'
        )

        st.markdown(table_html, unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Users
# ═══════════════════════════════════════════════════════════════════════════════
with tab_users:
    st.markdown("<div style='height:0.25rem'></div>", unsafe_allow_html=True)

    ROLE_COLORS = {
        "superadmin": "#7C3AED",
        "admin": "#407E3C",
        "technician": "#3B82F6",
        "viewer": "#6B7B6B",
        "client": "#F59E0B",
    }

    # Pre-load customers + departments for the create/edit forms
    from utils.cached_calls import cached_list_customers
    _cust_raw, _cust_err = cached_list_customers(st.session_state.get("access_token", ""), per_page=200)
    _cust_list = (_cust_raw.get("items", []) if _cust_raw else [])
    _cust_map = {c["name"]: c["id"] for c in _cust_list}
    _dept_raw, _dept_err = client.list_departments()
    _dept_list = (_dept_raw.get("departments", []) if _dept_raw else [])
    _dept_map = {"— None —": None, **{d["name"]: d["id"] for d in _dept_list}}
    if _cust_err or _dept_err:
        st.caption(f"⚠ Could not load some form options — {_cust_err or _dept_err}")

    # ── Create user form ──────────────────────────────────────────────────────
    with st.expander("+ Create New User", expanded=False):
        with st.form("create_user_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                new_name  = st.text_input("Full Name")
                new_email = st.text_input("Email")
            with c2:
                new_role  = st.selectbox("Role", ["technician", "viewer", "admin", "client"])
                new_pass  = st.text_input("Password", type="password", help="Min 10 characters")
            cc1, cc2 = st.columns(2)
            with cc1:
                new_dept_label = st.selectbox("Department", list(_dept_map.keys()), help="Assign to a department (optional for non-client roles)")
            with cc2:
                new_cust_label = st.selectbox(
                    "Customer (required for client role)",
                    ["— None —"] + list(_cust_map.keys()),
                    help="Required when role = client",
                )
            new_must_change = st.checkbox(
                "Require password change on first login",
                value=True,
            )
            submitted = st.form_submit_button("Create User", width='stretch')
            if submitted:
                if not new_name or not new_email or not new_pass:
                    st.error("Name, email, and password are required.")
                elif new_role == "client" and new_cust_label == "— None —":
                    st.error("Customer is required for client accounts.")
                else:
                    payload = {
                        "full_name": new_name,
                        "email": new_email,
                        "role": new_role,
                        "password": new_pass,
                        "must_change_password": new_must_change,
                        "department_id": _dept_map.get(new_dept_label),
                        "customer_id": _cust_map.get(new_cust_label) if new_cust_label != "— None —" else None,
                    }
                    _, cerr = client.create_user(payload)
                    if cerr:
                        st.error(f"Failed: {cerr}")
                    else:
                        st.success(f"User {new_email} created.")
                        st.rerun()

    st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

    # ── Toggle: show inactive ─────────────────────────────────────────────────
    show_inactive = st.checkbox("Show inactive accounts", value=False, key="users_show_inactive")

    # ── User list ─────────────────────────────────────────────────────────────
    users_data, users_err = client.list_users(include_inactive=show_inactive)
    if users_err:
        st.warning(f"Could not load users — {users_err}")
    else:
        user_list = users_data.get("items", []) if isinstance(users_data, dict) else users_data

        active_count = sum(1 for u in user_list if u.get("is_active", True))
        inactive_count = len(user_list) - active_count
        count_label = f"<b>{active_count}</b> active"
        if show_inactive and inactive_count:
            count_label += f" · <b>{inactive_count}</b> inactive"
        st.markdown(
            f'<div style="font-size:0.8rem;color:#6B7B6B;margin-bottom:0.6rem">{count_label}</div>',
            unsafe_allow_html=True,
        )

        current_uid = user.get("id", "")

        for u in user_list:
            uid   = u.get("id", "")
            uname = u.get("full_name") or "—"
            uemail = u.get("email", "—")
            urole = (u.get("role") or "viewer").lower()
            uactive = u.get("is_active", True)
            u_locked = u.get("is_locked", False)
            u_attempts = u.get("failed_login_attempts", 0)
            rc = ROLE_COLORS.get(urole, "#6B7B6B")
            created = fmt_datetime(u.get("created_at", ""))
            is_self = uid == current_uid

            # Build extra status badges HTML
            extra_badges = ""
            if not uactive:
                extra_badges += '<span style="background:#EF444415;color:#EF4444;padding:2px 8px;border-radius:5px;font-size:0.68rem;font-weight:700;border:1px solid #EF444433;margin-left:4px">INACTIVE</span>'
            if u_locked:
                extra_badges += '<span style="background:#EF444420;color:#DC2626;padding:2px 8px;border-radius:5px;font-size:0.68rem;font-weight:700;border:1px solid #DC262640;margin-left:4px">LOCKED</span>'
            elif u_attempts > 0:
                extra_badges += f'<span style="background:#F59E0B20;color:#B45309;padding:2px 8px;border-radius:5px;font-size:0.68rem;font-weight:700;border:1px solid #F59E0B33;margin-left:4px">⚠ {u_attempts} attempt(s)</span>'

            border_color = "#FECACA" if u_locked else ("#E5E7EB" if not uactive else "#DDE8DD")

            with st.container():
                col_info, col_actions = st.columns([4, 2])
                with col_info:
                    st.markdown(
                        f'<div style="background:#FFFFFF;border:1px solid {border_color};border-radius:10px;'
                        f'padding:0.75rem 1rem;margin-bottom:0.5rem">'
                        f'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">'
                        f'<div style="font-weight:600;color:{"#9CA3AF" if not uactive else "#1A1A1A"};font-size:0.88rem">{esc(uname)}</div>'
                        f'<span style="background:{rc}1A;color:{rc};padding:2px 8px;border-radius:5px;font-size:0.68rem;font-weight:700;border:1px solid {rc}33">{urole.upper()}</span>'
                        + extra_badges
                        + f'</div>'
                        f'<div style="font-size:0.78rem;color:#6B7B6B;margin-top:2px">{esc(uemail)} · Created {created}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                with col_actions:
                    if urole == "superadmin":
                        st.markdown(
                            '<div style="padding:0.4rem 0.75rem;border-radius:6px;background:#F3F0FF;'
                            'color:#7C3AED;font-size:0.75rem;font-weight:600;text-align:center;'
                            'border:1px solid #7C3AED33">Protected — use CLI</div>',
                            unsafe_allow_html=True,
                        )
                    elif not uactive:
                        # Inactive user — only show Reactivate
                        if st.button("Reactivate", key=f"react_btn_{uid}", width='stretch', type="primary"):
                            _, rerr = client.reactivate_user(uid)
                            if rerr:
                                st.error(f"Reactivate failed: {rerr}")
                            else:
                                st.success(f"{uname}'s account reactivated.")
                                st.rerun()
                    else:
                        if u_locked:
                            if st.button("Unlock Account", key=f"unlock_btn_{uid}", width='stretch', type="primary"):
                                _, uerr = client.unlock_user(uid)
                                if uerr:
                                    st.error(f"Unlock failed: {uerr}")
                                else:
                                    st.success(f"{uname}'s account unlocked.")
                                    st.rerun()
                        ea, da, dda = st.columns(3)
                        with ea:
                            if st.button("Edit", key=f"edit_btn_{uid}", width='stretch'):
                                st.session_state[f"edit_open_{uid}"] = not st.session_state.get(f"edit_open_{uid}", False)
                        with da:
                            if not is_self:
                                if st.button("Deactivate", key=f"deact_btn_{uid}", width='stretch'):
                                    st.session_state[f"deact_confirm_{uid}"] = True
                        with dda:
                            if not is_self:
                                if st.button("Delete", key=f"del_btn_{uid}", width='stretch'):
                                    st.session_state[f"del_confirm_{uid}"] = True

                # Deactivate confirmation
                if st.session_state.get(f"deact_confirm_{uid}"):
                    st.warning(f"Deactivate **{uname}** ({uemail})? They won't be able to log in. Reversible.")
                    cy, cn = st.columns(2)
                    with cy:
                        if st.button("Yes, deactivate", key=f"deact_yes_{uid}", width='stretch'):
                            _, derr = client.deactivate_user(uid)
                            if derr:
                                st.error(f"Failed: {derr}")
                            else:
                                st.success("Account deactivated.")
                                st.session_state.pop(f"deact_confirm_{uid}", None)
                                st.rerun()
                    with cn:
                        if st.button("Cancel", key=f"deact_no_{uid}", width='stretch'):
                            st.session_state.pop(f"deact_confirm_{uid}", None)
                            st.rerun()

                # Delete confirmation
                if st.session_state.get(f"del_confirm_{uid}"):
                    st.warning(f"Permanently delete **{uname}** ({uemail})? This cannot be undone.")
                    cy, cn = st.columns(2)
                    with cy:
                        if st.button("Yes, delete", key=f"del_yes_{uid}", width='stretch'):
                            _, derr = client.delete_user(uid)
                            if derr:
                                st.error(f"Failed: {derr}")
                            else:
                                st.success("User deleted.")
                                st.session_state.pop(f"del_confirm_{uid}", None)
                                st.rerun()
                    with cn:
                        if st.button("Cancel", key=f"del_no_{uid}", width='stretch'):
                            st.session_state.pop(f"del_confirm_{uid}", None)
                            st.rerun()

                # Edit form
                if st.session_state.get(f"edit_open_{uid}"):
                    with st.form(f"edit_user_{uid}"):
                        ec1, ec2 = st.columns(2)
                        _all_roles = ["technician", "viewer", "admin", "client"]
                        with ec1:
                            e_name = st.text_input("Full Name", value=uname)
                            e_role = st.selectbox("Role", _all_roles,
                                                  index=_all_roles.index(urole) if urole in _all_roles else 0)
                        with ec2:
                            e_pass = st.text_input("New Password (leave blank to keep)", type="password",
                                                   help="Min 10 chars · 1 uppercase · 1 number · 1 special char")
                        ecc1, ecc2 = st.columns(2)
                        with ecc1:
                            cur_dept_label = next((k for k, v in _dept_map.items() if v == u.get("department_id")), "— None —")
                            e_dept_label = st.selectbox("Department", list(_dept_map.keys()),
                                                        index=list(_dept_map.keys()).index(cur_dept_label) if cur_dept_label in _dept_map else 0)
                        with ecc2:
                            _cust_opts = ["— None —"] + list(_cust_map.keys())
                            cur_cust = next((c["name"] for c in _cust_list if c["id"] == u.get("customer_id")), "— None —")
                            e_cust_label = st.selectbox("Customer (client role)", _cust_opts,
                                                        index=_cust_opts.index(cur_cust) if cur_cust in _cust_opts else 0)
                        e_must_change = st.checkbox(
                            "Require password change on next login",
                            value=u.get("must_change_password", False),
                        )
                        save = st.form_submit_button("Save Changes", width='stretch')
                        if save:
                            payload = {
                                "full_name": e_name,
                                "role": e_role,
                                "must_change_password": e_must_change,
                                "department_id": _dept_map.get(e_dept_label),
                                "customer_id": _cust_map.get(e_cust_label) if e_cust_label != "— None —" else None,
                            }
                            if e_pass:
                                payload["password"] = e_pass
                            _, uerr = client.update_user(uid, payload)
                            if uerr:
                                st.error(f"Failed: {uerr}")
                            else:
                                st.success("User updated.")
                                st.session_state.pop(f"edit_open_{uid}", None)
                                st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 — Departments
# ═══════════════════════════════════════════════════════════════════════════════
with tab_depts:
    st.markdown("<div style='height:0.25rem'></div>", unsafe_allow_html=True)

    # ── Create department ─────────────────────────────────────────────────────
    with st.expander("+ Create New Department", expanded=False):
        with st.form("create_dept_form", clear_on_submit=True):
            d1, d2, d3 = st.columns([3, 2, 1])
            with d1:
                nd_name = st.text_input("Department Name *")
            with d2:
                nd_desc = st.text_input("Description (optional)")
            with d3:
                nd_color = st.text_input("Color (hex)", value="#407E3C")
            d_submit = st.form_submit_button("Create Department", width='stretch')
            if d_submit:
                if not nd_name.strip():
                    st.error("Department name is required.")
                else:
                    _, derr = client.create_department({
                        "name": nd_name.strip(),
                        "description": nd_desc.strip() or None,
                        "color": nd_color.strip() or "#407E3C",
                    })
                    if derr:
                        st.error(f"Failed: {derr}")
                    else:
                        st.success(f"Department '{nd_name}' created.")
                        st.rerun()

    st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

    # ── Department list ───────────────────────────────────────────────────────
    depts_data, depts_err = client.list_departments()
    if depts_err:
        st.warning(f"Could not load departments — {depts_err}")
    else:
        depts = (depts_data.get("departments", []) if depts_data else [])
        all_users_data, _ = client.list_users()
        all_users_list = (all_users_data.get("items", []) if all_users_data else [])

        if not depts:
            st.info("No departments yet. Create one above.")
        for dept in depts:
            did = dept["id"]
            dname = dept["name"]
            dcolor = dept.get("color", "#407E3C")
            ddesc = dept.get("description") or ""
            dmembers = dept.get("members", [])
            member_count = dept.get("member_count", len(dmembers))
            is_helpdesk = dname == "Help Desk"

            with st.expander(f"{dname}  ({member_count} member{'s' if member_count != 1 else ''})", expanded=False):
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:0.75rem">'
                    f'<div style="width:14px;height:14px;border-radius:50%;background:{dcolor}"></div>'
                    f'<span style="font-size:0.85rem;color:#6B7B6B">{esc(ddesc) or "No description"}</span>'
                    + (f'<span style="background:#407E3C1A;color:#407E3C;padding:2px 8px;border-radius:5px;font-size:0.7rem;font-weight:700;border:1px solid #407E3C33">BUILT-IN</span>' if is_helpdesk else "")
                    + '</div>',
                    unsafe_allow_html=True,
                )

                # Edit name/color (not for Help Desk name change)
                with st.form(f"edit_dept_{did}", clear_on_submit=False):
                    ed1, ed2, ed3 = st.columns([3, 2, 1])
                    with ed1:
                        e_dname = st.text_input("Name", value=dname, disabled=is_helpdesk)
                    with ed2:
                        e_ddesc = st.text_input("Description", value=ddesc)
                    with ed3:
                        e_dcolor = st.text_input("Color", value=dcolor)
                    de_save = st.form_submit_button("Save", width='stretch')
                    if de_save:
                        upd = {"description": e_ddesc, "color": e_dcolor}
                        if not is_helpdesk:
                            upd["name"] = e_dname
                        _, ue = client.update_department(did, upd)
                        if ue:
                            st.error(f"Failed: {ue}")
                        else:
                            st.success("Department updated.")
                            st.rerun()

                # Member management
                st.markdown(
                    '<div style="font-size:0.75rem;font-weight:700;text-transform:uppercase;'
                    'letter-spacing:0.07em;color:#6B7B6B;margin:0.75rem 0 0.4rem">Members</div>',
                    unsafe_allow_html=True,
                )
                member_ids = {m["id"] for m in dmembers}
                non_members = [u for u in all_users_list
                               if u["id"] not in member_ids and u.get("role") != "superadmin"]

                ma_col, mr_col = st.columns(2)
                with ma_col:
                    if non_members:
                        add_opts = {u.get("full_name") or u.get("email"): u["id"] for u in non_members}
                        add_label = st.selectbox("Add member", list(add_opts.keys()),
                                                 key=f"add_member_sel_{did}",
                                                 label_visibility="collapsed")
                        if st.button("Add", key=f"add_member_btn_{did}", width='stretch'):
                            _, me = client.set_department_member(did, add_opts[add_label], "add")
                            if me:
                                st.error(f"Failed: {me}")
                            else:
                                st.rerun()
                    else:
                        st.caption("All users already assigned.")

                with mr_col:
                    if dmembers:
                        rm_opts = {u.get("full_name") or u.get("email"): u["id"] for u in dmembers}
                        rm_label = st.selectbox("Remove member", list(rm_opts.keys()),
                                                key=f"rm_member_sel_{did}",
                                                label_visibility="collapsed")
                        if st.button("Remove", key=f"rm_member_btn_{did}", width='stretch'):
                            _, me = client.set_department_member(did, rm_opts[rm_label], "remove")
                            if me:
                                st.error(f"Failed: {me}")
                            else:
                                st.rerun()
                    else:
                        st.caption("No members yet.")

                # Delete dept (not Help Desk)
                if not is_helpdesk:
                    st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)
                    if st.button("Delete Department", key=f"del_dept_{did}", type="secondary"):
                        st.session_state[f"del_dept_confirm_{did}"] = True
                    if st.session_state.get(f"del_dept_confirm_{did}"):
                        st.warning(f"Delete **{dname}**? Members will be unassigned.")
                        dc1, dc2 = st.columns(2)
                        with dc1:
                            if st.button("Yes, delete", key=f"del_dept_yes_{did}", width='stretch'):
                                _, de = client.delete_department(did)
                                if de:
                                    st.error(f"Failed: {de}")
                                else:
                                    st.session_state.pop(f"del_dept_confirm_{did}", None)
                                    st.rerun()
                        with dc2:
                            if st.button("Cancel", key=f"del_dept_no_{did}", width='stretch'):
                                st.session_state.pop(f"del_dept_confirm_{did}", None)
                                st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 5 — Org Settings
# ═══════════════════════════════════════════════════════════════════════════════
with tab_org:
    st.markdown("<div style='height:0.25rem'></div>", unsafe_allow_html=True)

    import base64 as _b64

    org_data, org_err = client.get_org_settings()
    if org_err:
        st.warning(f"Could not load org settings — {org_err}")
        org_data = {}

    org = org_data or {}

    # ── Company details form ──────────────────────────────────────────────────
    st.markdown(
        f'<div style="font-size:0.75rem;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.07em;color:#6B7B6B;margin-bottom:0.75rem">Company Information</div>',
        unsafe_allow_html=True,
    )

    with st.form("org_settings_form"):
        oc1, oc2 = st.columns(2)
        with oc1:
            org_name    = st.text_input("Company Name",    value=org.get("company_name", ""))
            org_email   = st.text_input("Billing Email",   value=org.get("company_email", ""))
            org_terms   = st.selectbox(
                "Payment Terms",
                ["Net 7", "Net 14", "Net 30", "Net 45", "Net 60", "Due on Receipt"],
                index=["Net 7","Net 14","Net 30","Net 45","Net 60","Due on Receipt"].index(
                    org.get("payment_terms","Net 30")
                ) if org.get("payment_terms","Net 30") in ["Net 7","Net 14","Net 30","Net 45","Net 60","Due on Receipt"] else 2,
            )
        with oc2:
            org_phone   = st.text_input("Phone",           value=org.get("company_phone", ""))
            org_address = st.text_area("Address",          value=org.get("company_address", ""), height=70)

        org_bank    = st.text_area("Bank / Payment Details",
                                   value=org.get("bank_details", ""),
                                   height=80,
                                   placeholder="e.g. Bank: HSBC, Sort: 12-34-56, Account: 87654321\nPayPal: billing@company.com")
        org_footer  = st.text_input("Invoice Footer Message",
                                    value=org.get("footer_notes", "Thank you for your business!"))

        save_org = st.form_submit_button("Save Settings", width='content')

    if save_org:
        payload = {
            "company_name":    org_name,
            "company_email":   org_email,
            "company_phone":   org_phone,
            "company_address": org_address,
            "payment_terms":   org_terms,
            "bank_details":    org_bank,
            "footer_notes":    org_footer,
        }
        _, serr = client.update_org_settings(payload)
        if serr:
            st.error(f"Failed to save: {serr}")
        else:
            st.success("Org settings saved.")
            st.rerun()

    # ── White-label branding ─────────────────────────────────────────────────
    st.markdown("<div style='height:1.5rem'></div>", unsafe_allow_html=True)
    st.markdown(
        f'<div style="font-size:0.75rem;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.07em;color:#6B7B6B;margin-bottom:0.75rem">White-Label Branding</div>',
        unsafe_allow_html=True,
    )

    with st.form("branding_form"):
        bc1, bc2 = st.columns(2)
        with bc1:
            brand_name  = st.text_input("App Name",
                                         value=org.get("app_name", "RMM System"),
                                         help="Shown on login page, browser tab, and sidebar")
            brand_color = st.text_input("Primary Color (hex)",
                                         value=org.get("primary_color", "#407E3C"),
                                         help="e.g. #2563EB for blue, #DC2626 for red")
        with bc2:
            brand_tagline = st.text_input("Tagline",
                                           value=org.get("tagline", "Remote Monitoring & Management"),
                                           help="Sub-heading shown below app name on login page")
            st.markdown(
                f'<div style="margin-top:1.6rem;width:100%;height:40px;border-radius:7px;'
                f'background:{org.get("primary_color","#407E3C")};display:flex;align-items:center;'
                f'justify-content:center;color:#fff;font-weight:600;font-size:0.85rem">'
                f'Color Preview</div>',
                unsafe_allow_html=True,
            )
        save_brand = st.form_submit_button("Save Branding", width='content')

    if save_brand:
        import re
        if brand_color and not re.match(r'^#[0-9A-Fa-f]{6}$', brand_color):
            st.error("Primary color must be a valid hex code (e.g. #407E3C)")
        else:
            _, berr = client.update_org_settings({
                "app_name":      brand_name,
                "tagline":       brand_tagline,
                "primary_color": brand_color,
            })
            if berr:
                st.error(f"Failed: {berr}")
            else:
                # Bust branding cache so sidebar + login reflect changes immediately
                st.session_state.pop("_branding", None)
                st.session_state.pop("_branding_ts", None)
                st.success("Branding saved. Reload the page to see changes.")
                st.rerun()

    # ── Logo management ───────────────────────────────────────────────────────
    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
    st.markdown(
        f'<div style="font-size:0.75rem;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.07em;color:#6B7B6B;margin-bottom:0.75rem">Company Logo</div>',
        unsafe_allow_html=True,
    )

    logo_col, upload_col = st.columns([1, 2])

    with logo_col:
        logo_data = org.get("logo_data") or ""
        if logo_data:
            try:
                _, b64_part = logo_data.split(",", 1)
                logo_bytes = _b64.b64decode(b64_part)
                st.image(logo_bytes, width=180, caption="Current logo")
            except Exception:
                st.info("Logo preview unavailable.")
        else:
            st.markdown(
                '<div style="width:180px;height:70px;border-radius:8px;border:2px dashed #DDE8DD;'
                'display:flex;align-items:center;justify-content:center;color:#9CA3AF;font-size:0.8rem">'
                'No logo set</div>',
                unsafe_allow_html=True,
            )

    with upload_col:
        st.markdown("<div style='height:0.25rem'></div>", unsafe_allow_html=True)
        logo_file = st.file_uploader(
            "Upload logo (PNG, JPG — max 2 MB)",
            type=["png", "jpg", "jpeg", "webp"],
            key="org_logo_uploader",
        )
        lu1, lu2 = st.columns(2)
        with lu1:
            if st.button("Save Logo", width='stretch', disabled=logo_file is None):
                if logo_file:
                    with st.spinner("Uploading..."):
                        _, lerr = client.upload_org_logo(logo_file.read(), logo_file.type)
                    if lerr:
                        st.error(f"Upload failed: {lerr}")
                    else:
                        st.success("Logo updated.")
                        st.rerun()
        with lu2:
            if logo_data:
                if st.button("Remove Logo", width='stretch'):
                    _, rerr = client.delete_org_logo()
                    if rerr:
                        st.error(f"Remove failed: {rerr}")
                    else:
                        st.success("Logo removed.")
                        st.rerun()

    # ── Regional Settings ─────────────────────────────────────────────────────
    st.markdown("<div style='height:1.5rem'></div>", unsafe_allow_html=True)
    st.markdown(
        f'<div style="font-size:0.75rem;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.07em;color:#6B7B6B;margin-bottom:0.75rem">Regional Settings</div>',
        unsafe_allow_html=True,
    )

    with st.form("regional_form"):
        rc1, rc2 = st.columns(2)
        with rc1:
            _cur_currency = org.get("currency", "USD")
            currency_labels = {
                "USD": "USD — US Dollar ($)",
                "EUR": "EUR — Euro (€)",
                "GBP": "GBP — British Pound (£)",
                "CHF": "CHF — Swiss Franc (Fr)",
                "CAD": "CAD — Canadian Dollar (CA$)",
                "AUD": "AUD — Australian Dollar (A$)",
                "JPY": "JPY — Japanese Yen (¥)",
                "SEK": "SEK — Swedish Krona (kr)",
                "NOK": "NOK — Norwegian Krone (kr)",
                "DKK": "DKK — Danish Krone (kr)",
            }
            currency_opts = list(currency_labels.values())
            cur_idx = SUPPORTED_CURRENCIES.index(_cur_currency) if _cur_currency in SUPPORTED_CURRENCIES else 0
            sel_currency_label = st.selectbox(
                "Currency",
                currency_opts,
                index=cur_idx,
                help="Used on invoices and billing totals throughout the dashboard.",
            )
            sel_currency = SUPPORTED_CURRENCIES[currency_opts.index(sel_currency_label)]

        with rc2:
            _cur_tz = org.get("timezone", "UTC")
            tz_idx = SUPPORTED_TIMEZONES.index(_cur_tz) if _cur_tz in SUPPORTED_TIMEZONES else 0
            sel_timezone = st.selectbox(
                "Timezone",
                SUPPORTED_TIMEZONES,
                index=tz_idx,
                help="Timestamps in alerts, audit log, and reports will display in this timezone.",
            )

        save_regional = st.form_submit_button("Save Regional Settings", width='content')

    if save_regional:
        _, rerr = client.update_org_settings({"currency": sel_currency, "timezone": sel_timezone})
        if rerr:
            st.error(f"Failed: {rerr}")
        else:
            st.session_state.pop("_org_settings", None)
            st.success(f"Saved — currency: {sel_currency}, timezone: {sel_timezone}. Reload pages to apply.")

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 6 — AI Triage
# ═══════════════════════════════════════════════════════════════════════════════
with tab_triage:
    st.markdown("<div style='height:0.25rem'></div>", unsafe_allow_html=True)
    st.markdown(
        '<div style="font-size:0.82rem;color:#6B7B6B;margin-bottom:1rem">'
        'Every new ticket is automatically categorized by AI. A category only auto-resolves '
        'tickets (replies to the customer and closes the ticket) when <b>Auto-resolve</b> is on '
        'below. While <b>Shadow mode</b> is also on, the AI drafts a reply but a technician must '
        'approve it on the ticket before anything is sent — flip Shadow mode off only once you '
        'trust that category\'s accuracy on real tickets.</div>',
        unsafe_allow_html=True,
    )

    with st.spinner("Loading categories…"):
        cats_data, cats_err = client.list_triage_categories()
    if cats_err:
        st.warning(f"Could not load triage categories — {cats_err}")
        cats_data = []

    for cat in (cats_data or []):
        cid = cat["id"]
        st.markdown(
            f'<div style="{CARD}">'
            f'<div style="font-weight:700;color:#1A1A1A;font-size:0.92rem">{esc(cat["label"])}</div>'
            f'<div style="font-size:0.8rem;color:#6B7B6B;margin-bottom:0.5rem">{esc(cat.get("description") or "")}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        c1, c2, c3, c4, c5 = st.columns([1.1, 1.1, 1.3, 1.1, 0.9])
        with c1:
            new_active = st.checkbox("Active", value=cat.get("is_active", True), key=f"triage_active_{cid}")
        with c2:
            new_auto = st.checkbox("Auto-resolve", value=cat.get("auto_resolve_enabled", False), key=f"triage_auto_{cid}")
        with c3:
            new_shadow = st.checkbox("Shadow mode (requires approval)", value=cat.get("shadow_mode", True), key=f"triage_shadow_{cid}")
        with c4:
            new_threshold = st.slider("Min confidence", 0.0, 1.0, float(cat.get("confidence_threshold", 0.85)),
                                      step=0.05, key=f"triage_thresh_{cid}")
        with c5:
            if st.button("Save", key=f"triage_save_{cid}", width='stretch'):
                _, serr = client.update_triage_category(cid, {
                    "is_active": new_active, "auto_resolve_enabled": new_auto,
                    "shadow_mode": new_shadow, "confidence_threshold": new_threshold,
                })
                if serr:
                    st.error(f"Save failed: {serr}")
                else:
                    st.success(f"Saved {cat['label']}.")
                    st.rerun()
        st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

render_ai_assistant("Admin Panel", {"context": "navigation_only"})
