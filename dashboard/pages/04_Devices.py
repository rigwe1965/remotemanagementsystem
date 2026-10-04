"""Devices — OS filter tabs, agent devices + agentless (WiFi/mobile)."""
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

from utils.auth import require_auth
from utils.nav import render_sidebar
from utils.ai_assistant import render_ai_assistant
from utils.styles import inject_css, badge, plotly_layout, BRAND, STATUS_COLORS
from utils.formatters import fmt_datetime, fmt_uptime, pct_color
from utils.sanitize import esc

st.set_page_config(page_title="Devices — RMM", layout="wide")
inject_css()

client = require_auth()
render_sidebar()

st.markdown("""
<h1 style="margin:0">Devices</h1>
<p style="color:#6B7B6B;margin:2px 0 1rem;font-size:0.88rem">
All registered endpoints — agent-managed and agentless (WiFi discovered)</p>
""", unsafe_allow_html=True)

PLATFORM_ICON = {
    "windows": "Win", "mac": "Mac", "linux": "Lin",
    "android": "And", "ios": "iOS", "unknown": "—", "agentless": "—",
}

PLATFORM_ICON_HTML = {
    "windows": '<i class="fa-brands fa-windows"></i>',
    "mac":     '<i class="fa-brands fa-apple"></i>',
    "linux":   '<i class="fa-brands fa-linux"></i>',
    "android": '<i class="fa-brands fa-android"></i>',
    "ios":     '<i class="fa-brands fa-apple"></i>',
    "unknown": '<i class="fa-solid fa-question"></i>',
}

# ── Load all devices + platform counts + update info (parallel) ──────────────
from concurrent.futures import ThreadPoolExecutor
with st.spinner("Loading devices..."):
    with ThreadPoolExecutor(max_workers=3) as _ex:
        _f1 = _ex.submit(client.list_devices, per_page=200)
        _f2 = _ex.submit(client.get_platform_counts)
        _f3 = _ex.submit(client.get_agent_update_info)
        data, err = _f1.result()
        counts_data, _ = _f2.result()
        _upd_info, _ = _f3.result()

_latest_agent_version = (_upd_info or {}).get("latest_version", "")
_download_available = (_upd_info or {}).get("download_available", False)

if err:
    st.warning(f"Could not load devices — {err}")
    st.stop()

all_devices = data.get("items", [])
pc = (counts_data or {}).get("by_platform", {})
ag = (counts_data or {}).get("agentless", 0)
total = len(all_devices)

# ── Auto-highlight device linked from Overview health map ─────────────────────
# Check session state (from st.switch_page) then query param (from direct URL)
_linked_device_id = st.session_state.pop("_nav_device", None) or st.query_params.get("device", "")
_linked_hostname = ""
if _linked_device_id:
    _match = next((d for d in all_devices if str(d.get("id")) == str(_linked_device_id)), None)
    if _match:
        _linked_hostname = _match.get("hostname", "")
        st.info(f"Showing device: **{_linked_hostname}**")

# ── Shared search + status filter (apply inside each tab) ─────────────────────
sf1, sf2, sf3, sf4 = st.columns([2, 1.2, 1.2, 0.9])
with sf1:
    _default_search = _linked_hostname if _linked_device_id and _linked_hostname else ""
    search = st.text_input("Search hostname / IP", value=_default_search, placeholder="e.g. DESKTOP- or 192.168.", label_visibility="collapsed")
with sf2:
    status_filter = st.selectbox("Status", ["All statuses", "healthy", "warning", "critical", "offline"],
                                  label_visibility="collapsed")
with sf3:
    online_filter = st.selectbox("Online", ["All devices", "Online only", "Offline only"],
                                  label_visibility="collapsed")
with sf4:
    _export_placeholder = st.empty()  # filled after _apply_filters is defined


def _apply_filters(devices: list) -> list:
    out = devices
    if search:
        s = search.lower()
        out = [d for d in out if s in (d.get("hostname") or "").lower()
               or s in (d.get("ip_address") or "").lower()]
    if status_filter != "All statuses":
        out = [d for d in out if d.get("status") == status_filter]
    if online_filter == "Online only":
        out = [d for d in out if d.get("is_online")]
    elif online_filter == "Offline only":
        out = [d for d in out if not d.get("is_online")]
    return out


def _tab_devices(tab_name: str) -> list:
    platform_map = {
        "Windows": "windows", "macOS": "mac", "Linux": "linux",
        "Android": "android", "iOS": "ios",
    }
    if tab_name == "All":
        return _apply_filters(all_devices)
    if tab_name == "Agentless":
        return _apply_filters([d for d in all_devices if d.get("is_agentless")])
    p = platform_map.get(tab_name)
    return _apply_filters([d for d in all_devices if d.get("platform") == p])


# ── CSV export (all devices matching current filters) ─────────────────────────
_filtered_all = _apply_filters(all_devices)
if _filtered_all:
    _export_df = pd.DataFrame([{
        "Hostname": d.get("hostname", ""), "IP": d.get("ip_address", ""),
        "Platform": d.get("platform", ""), "Status": d.get("status", ""),
        "Online": d.get("is_online", False), "Customer": d.get("customer_name", ""),
        "CPU%": (d.get("latest_metrics") or {}).get("cpu_pct", ""),
        "RAM%": (d.get("latest_metrics") or {}).get("ram_pct", ""),
        "Disk%": (d.get("latest_metrics") or {}).get("disk_pct", ""),
        "Last Seen": d.get("last_seen", ""),
    } for d in _filtered_all])
    _export_placeholder.download_button(
        "Export CSV", data=_export_df.to_csv(index=False).encode("utf-8"),
        file_name="devices.csv", mime="text/csv", width='stretch',
    )

# ── OS Tabs ───────────────────────────────────────────────────────────────────
tab_labels = [
    f"All ({total})",
    f"Windows ({pc.get('windows', 0)})",
    f"macOS ({pc.get('mac', 0)})",
    f"Linux ({pc.get('linux', 0)})",
    f"Android ({pc.get('android', 0)})",
    f"iOS ({pc.get('ios', 0)})",
    f"Agentless ({ag})",
]
tab_names = ["All", "Windows", "macOS", "Linux", "Android", "iOS", "Agentless"]
tabs = st.tabs(tab_labels)

# ── Helper: percent bar ───────────────────────────────────────────────────────
def _pct_bar(pct: float, color: str) -> str:
    return (
        f'<div style="background:#EEF2EE;border-radius:3px;height:4px;margin-top:3px">'
        f'<div style="background:{color};width:{min(pct,100):.0f}%;height:4px;border-radius:3px"></div></div>'
    )


# ── Agentless device row ──────────────────────────────────────────────────────
def _render_agentless_row(device: dict, tab_key: str = ""):
    is_online = device.get("is_online", False)
    dot_color = "#22C55E" if is_online else "#8492A6"
    platform = device.get("platform", "unknown")
    icon = PLATFORM_ICON.get(platform, "—")
    dev_type = device.get("device_type", "unknown")

    with st.expander(
        f'{icon}  {device.get("hostname", device.get("ip_address", "—"))}   '
        f'{"● Online" if is_online else "○ Offline"}  ·  '
        f'{device.get("vendor") or "Unknown vendor"}  ·  '
        f'{platform.upper()}  ·  AGENTLESS',
    ):
        c1, c2 = st.columns(2)

        with c1:
            st.markdown(f"""
<div style="background:#FAFCFA;border-radius:8px;padding:0.85rem 1rem;border:1px solid #E8EEE8">
    <div style="font-size:0.72rem;font-weight:700;text-transform:uppercase;
                letter-spacing:0.07em;color:#6B7B6B;margin-bottom:0.6rem">Network</div>
    <table style="width:100%;border-collapse:collapse;font-size:0.83rem">
        <tr><td style="color:#6B7B6B;padding:2px 0;width:40%">IP</td>
            <td style="color:#1A1A1A;font-family:monospace;font-weight:600">{esc(device.get('ip_address','—'))}</td></tr>
        <tr><td style="color:#6B7B6B;padding:2px 0">MAC</td>
            <td style="color:#1A1A1A;font-family:monospace;font-size:0.8rem">{esc(device.get('mac_address','—'))}</td></tr>
        <tr><td style="color:#6B7B6B;padding:2px 0">Vendor</td>
            <td style="color:#1A1A1A">{esc(device.get('vendor','Unknown'))}</td></tr>
        <tr><td style="color:#6B7B6B;padding:2px 0">Platform</td>
            <td style="color:#1A1A1A">{PLATFORM_ICON_HTML.get(platform, "")} {platform}</td></tr>
        <tr><td style="color:#6B7B6B;padding:2px 0">Device type</td>
            <td style="color:#1A1A1A;text-transform:capitalize">{dev_type}</td></tr>
        <tr><td style="color:#6B7B6B;padding:2px 0">Last seen</td>
            <td style="color:#1A1A1A">{fmt_datetime(device.get('last_seen'))}</td></tr>
    </table>
</div>""", unsafe_allow_html=True)

        with c2:
            st.markdown(f"""
<div style="background:#FAFCFA;border-radius:8px;padding:0.85rem 1rem;border:1px solid #E8EEE8;height:100%">
    <div style="font-size:0.72rem;font-weight:700;text-transform:uppercase;
                letter-spacing:0.07em;color:#6B7B6B;margin-bottom:0.6rem">Status</div>
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:0.5rem">
        <div style="width:10px;height:10px;border-radius:50%;background:{dot_color};
                    box-shadow:0 0 5px {dot_color}88"></div>
        <span style="font-size:0.88rem;font-weight:600;color:#1A1A1A">
            {"Online" if is_online else "Offline"}</span>
    </div>
    <div style="font-size:0.78rem;color:#6B7B6B;margin-bottom:0.75rem">
        Agentless — ping-monitored only.<br>
        Remote actions not available without an agent.
    </div>
</div>""", unsafe_allow_html=True)

        # Assign to customer
        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
        cust_data, cust_err = client.list_customers(per_page=200)
        if cust_err:
            st.caption(f"⚠ Could not load customers — {cust_err}")
        customers = (cust_data or {}).get("items", [])
        cust_options = {c["id"]: c["name"] for c in customers}
        cust_ids = [""] + list(cust_options.keys())
        cust_labels = ["— Unassigned —"] + list(cust_options.values())
        current_cid = device.get("customer_id") or ""
        current_idx = cust_ids.index(current_cid) if current_cid in cust_ids else 0

        ca1, ca2, ca3, ca4, ca5 = st.columns([2.5, 0.8, 0.9, 0.9, 0.8])
        with ca1:
            chosen_idx = st.selectbox(
                "Assign to Customer",
                range(len(cust_ids)),
                format_func=lambda x: cust_labels[x],
                index=current_idx,
                key=f"cust_{tab_key}_{device['id']}",
            )
        with ca2:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            if st.button("Save", key=f"save_cust_{tab_key}_{device['id']}"):
                new_cid = cust_ids[chosen_idx] or None
                _, e = client.update_device(device["id"], {"customer_id": new_cid})
                st.error(f"Failed: {e}") if e else st.success(f"Assigned to {cust_labels[chosen_idx]}")
                if not e:
                    st.rerun()
        with ca3:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            if st.button("Edit", icon=":material/edit:", key=f"edit_{tab_key}_{device['id']}", width='stretch'):
                st.session_state[f"ag_edit_{device['id']}"] = not st.session_state.get(f"ag_edit_{device['id']}", False)
        with ca4:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            if st.button("Ping", icon=":material/wifi_tethering:", key=f"ping_{tab_key}_{device['id']}", width='stretch'):
                result, e = client.ping_check_device(device["id"])
                if e:
                    st.error(f"Ping failed: {e}")
                else:
                    online = (result or {}).get("is_online", False)
                    if online:
                        st.success("Device is reachable ✓")
                    else:
                        st.warning("No response — device may be offline or blocking ICMP")
                    st.rerun()
        with ca5:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            _confirm_key = f"del_confirm_{tab_key}_{device['id']}"
            if st.session_state.get(_confirm_key):
                st.warning("Sure?")
                cc1, cc2 = st.columns(2)
                with cc1:
                    if st.button("Yes", key=f"del_yes_{tab_key}_{device['id']}", width='stretch'):
                        st.session_state.pop(_confirm_key, None)
                        _, e = client.delete_device(device["id"])
                        st.error(f"Delete failed: {e}") if e else st.rerun()
                with cc2:
                    if st.button("No", key=f"del_no_{tab_key}_{device['id']}", width='stretch'):
                        st.session_state.pop(_confirm_key, None)
                        st.rerun()
            else:
                if st.button("", icon=":material/delete:", key=f"del_{tab_key}_{device['id']}", width='stretch'):
                    st.session_state[_confirm_key] = True
                    st.rerun()

        # Edit form
        if st.session_state.get(f"ag_edit_{device['id']}"):
            PLATFORMS = ["unknown", "windows", "mac", "linux", "android", "ios"]
            DEVICE_TYPES = ["unknown", "desktop", "laptop", "mobile", "server"]
            cur_platform = device.get("platform", "unknown")
            cur_dtype = device.get("device_type", "unknown")
            p_idx = PLATFORMS.index(cur_platform) if cur_platform in PLATFORMS else 0
            d_idx = DEVICE_TYPES.index(cur_dtype) if cur_dtype in DEVICE_TYPES else 0
            with st.form(key=f"ag_edit_form_{tab_key}_{device['id']}"):
                ef1, ef2, ef3 = st.columns(3)
                with ef1:
                    new_hostname = st.text_input("Friendly name / hostname", value=device.get("hostname") or device.get("ip_address", ""))
                with ef2:
                    new_platform = st.selectbox("Platform", PLATFORMS, index=p_idx)
                with ef3:
                    new_dtype = st.selectbox("Device type", DEVICE_TYPES, index=d_idx)
                if st.form_submit_button("Save device info", width='stretch'):
                    _, e = client.update_device(device["id"], {
                        "hostname": new_hostname,
                        "platform": new_platform,
                        "device_type": new_dtype,
                    })
                    if e:
                        st.error(f"Failed: {e}")
                    else:
                        st.session_state.pop(f"ag_edit_{device['id']}", None)
                        st.rerun()


# ── MDM-managed mobile device row (Android, real remote actions) ──────────────
def _render_mobile_managed_row(device: dict, tab_key: str = ""):
    is_online = device.get("is_online", False)
    dot_color = "#22C55E" if is_online else "#8492A6"
    platform = device.get("platform", "unknown")
    icon = PLATFORM_ICON.get(platform, "—")
    enrollment = device.get("mdm_enrollment") or {}
    ownership = enrollment.get("ownership_type", "byod")
    compliant = enrollment.get("policy_compliant")

    with st.expander(
        f'{icon}  {device.get("display_name") or device.get("hostname", "—")}   '
        f'{"● Online" if is_online else "○ Offline"}  ·  '
        f'{ownership.upper()}  ·  MANAGED',
    ):
        c1, c2 = st.columns(2)
        with c1:
            comp_txt = "Compliant" if compliant else ("Non-compliant" if compliant is False else "Unknown")
            comp_color = "#22C55E" if compliant else ("#EF4444" if compliant is False else "#8492A6")
            st.markdown(f"""
<div style="background:#FAFCFA;border-radius:8px;padding:0.85rem 1rem;border:1px solid #E8EEE8">
    <div style="font-size:0.72rem;font-weight:700;text-transform:uppercase;
                letter-spacing:0.07em;color:#6B7B6B;margin-bottom:0.6rem">Managed Device</div>
    <table style="width:100%;border-collapse:collapse;font-size:0.83rem">
        <tr><td style="color:#6B7B6B;padding:2px 0;width:40%">Ownership</td>
            <td style="color:#1A1A1A;text-transform:capitalize">{ownership}</td></tr>
        <tr><td style="color:#6B7B6B;padding:2px 0">Compliance</td>
            <td style="color:{comp_color};font-weight:600">{comp_txt}</td></tr>
        <tr><td style="color:#6B7B6B;padding:2px 0">OS</td>
            <td style="color:#1A1A1A">{esc(device.get('os_name','—'))} {esc(device.get('os_version') or '')}</td></tr>
        <tr><td style="color:#6B7B6B;padding:2px 0">Vendor</td>
            <td style="color:#1A1A1A">{esc(device.get('vendor') or 'Unknown')}</td></tr>
        <tr><td style="color:#6B7B6B;padding:2px 0">Last seen</td>
            <td style="color:#1A1A1A">{fmt_datetime(device.get('last_seen'))}</td></tr>
    </table>
</div>""", unsafe_allow_html=True)
        with c2:
            st.markdown(f"""
<div style="background:#FAFCFA;border-radius:8px;padding:0.85rem 1rem;border:1px solid #E8EEE8;height:100%">
    <div style="font-size:0.72rem;font-weight:700;text-transform:uppercase;
                letter-spacing:0.07em;color:#6B7B6B;margin-bottom:0.6rem">Status</div>
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:0.5rem">
        <div style="width:10px;height:10px;border-radius:50%;background:{dot_color};
                    box-shadow:0 0 5px {dot_color}88"></div>
        <span style="font-size:0.88rem;font-weight:600;color:#1A1A1A">
            {"Online" if is_online else "Offline"}</span>
    </div>
    <div style="font-size:0.78rem;color:#6B7B6B">
        Managed via Android Management API — no custom agent installed.
        Commands apply when the device next checks in.
    </div>
</div>""", unsafe_allow_html=True)

        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
        # Server enforces role/scope on every command below (mobile_mdm.py's
        # _require_role + _mdm_scope_check) — buttons are shown to all viewers
        # of this expander, the API call itself is what's actually gated.
        b1, b2, b3, b4, b5 = st.columns(5)
        with b1:
            if st.button("Lock", icon=":material/lock:", key=f"mdm_lock_{tab_key}_{device['id']}", width='stretch'):
                _, e = client.mdm_lock_device(device["id"])
                st.error(f"Failed: {e}") if e else st.success("Lock command sent")
        with b2:
            if st.button("Lost Mode", icon=":material/error:", key=f"mdm_lost_{tab_key}_{device['id']}", width='stretch'):
                _, e = client.mdm_start_lost_mode(device["id"])
                st.error(f"Failed: {e}") if e else st.success("Lost Mode command sent")
        with b3:
            if st.button("Reboot", icon=":material/restart_alt:", key=f"mdm_reboot_{tab_key}_{device['id']}", width='stretch'):
                _, e = client.mdm_reboot_device(device["id"])
                st.error(f"Failed: {e}") if e else st.success("Reboot command sent")
        with b4:
            if st.button("Reset Passcode", icon=":material/key:", key=f"mdm_reset_{tab_key}_{device['id']}", width='stretch'):
                _, e = client.mdm_reset_password_device(device["id"])
                st.error(f"Failed: {e}") if e else st.success("Reset passcode command sent")
        with b5:
            _wipe_key = f"mdm_wipe_confirm_{tab_key}_{device['id']}"
            if st.session_state.get(_wipe_key):
                st.warning("Wipe is irreversible. Confirm?")
                wc1, wc2 = st.columns(2)
                with wc1:
                    if st.button("Yes, wipe", key=f"mdm_wipe_yes_{tab_key}_{device['id']}", width='stretch'):
                        st.session_state.pop(_wipe_key, None)
                        _, e = client.mdm_wipe_device(device["id"])
                        st.error(f"Failed: {e}") if e else st.success("Wipe command sent")
                with wc2:
                    if st.button("Cancel", key=f"mdm_wipe_no_{tab_key}_{device['id']}", width='stretch'):
                        st.session_state.pop(_wipe_key, None)
                        st.rerun()
            else:
                if st.button("Wipe", icon=":material/delete_forever:", key=f"mdm_wipe_{tab_key}_{device['id']}", width='stretch'):
                    st.session_state[_wipe_key] = True
                    st.rerun()


# ── Version comparison helper ─────────────────────────────────────────────────
def _ver_tuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in (v or "").strip().split("."))
    except Exception:
        return (0,)


# ── Agent device row (original full row) ─────────────────────────────────────
def _render_agent_row(device: dict, tab_key: str = "", latest_version: str = ""):
    status   = device.get("status", "unknown")
    s_color  = STATUS_COLORS.get(status, "#8492A6")
    is_online = device.get("is_online", False)
    dot_color = "#22C55E" if is_online else "#8492A6"
    platform = device.get("platform", "unknown")
    icon = PLATFORM_ICON.get(platform, "—")
    metrics  = device.get("latest_metrics") or {}
    cpu  = metrics.get("cpu_pct",  0) or 0
    ram  = metrics.get("ram_pct",  0) or 0
    disk = metrics.get("disk_pct", 0) or 0
    cpu_c  = pct_color(cpu)
    ram_c  = pct_color(ram)
    disk_c = pct_color(disk)

    agent_ver = device.get("agent_version") or ""
    update_available = bool(
        latest_version and agent_ver
        and _ver_tuple(latest_version) > _ver_tuple(agent_ver)
    )
    update_tag = "  ⬆ UPDATE" if update_available else ""

    selected = st.session_state.get("selected_device_id")

    with st.expander(
        f'{icon} {"●" if is_online else "○"}  {device.get("hostname","—")}   '
        f'CPU {cpu:.0f}%  ·  RAM {ram:.0f}%  ·  Disk {disk:.0f}%  '
        f'·  {status.upper()}{update_tag}',
        expanded=(device.get("id") == selected),
    ):
        d1, d2, d3 = st.columns(3)

        with d1:
            st.markdown(f"""
<div style="background:#FAFCFA;border-radius:8px;padding:0.85rem 1rem;border:1px solid #E8EEE8">
    <div style="font-size:0.72rem;font-weight:700;text-transform:uppercase;
                letter-spacing:0.07em;color:#6B7B6B;margin-bottom:0.6rem">System</div>
    <table style="width:100%;border-collapse:collapse;font-size:0.83rem">
        <tr><td style="color:#6B7B6B;padding:2px 0;width:40%">Hostname</td>
            <td style="color:#1A1A1A;font-weight:500">{esc(device.get('hostname','—'))}</td></tr>
        <tr><td style="color:#6B7B6B;padding:2px 0">IP</td>
            <td style="color:#1A1A1A">{esc(device.get('ip_address','—'))}</td></tr>
        <tr><td style="color:#6B7B6B;padding:2px 0">OS</td>
            <td style="color:#1A1A1A">{PLATFORM_ICON_HTML.get(platform, "")} {esc(device.get('os_name') or '—')} {esc(device.get('os_version',''))}</td></tr>
        <tr><td style="color:#6B7B6B;padding:2px 0">Platform</td>
            <td style="color:#1A1A1A">{esc(device.get('platform','—'))}</td></tr>
    </table>
</div>""", unsafe_allow_html=True)

        with d2:
            st.markdown(f"""
<div style="background:#FAFCFA;border-radius:8px;padding:0.85rem 1rem;border:1px solid #E8EEE8">
    <div style="font-size:0.72rem;font-weight:700;text-transform:uppercase;
                letter-spacing:0.07em;color:#6B7B6B;margin-bottom:0.6rem">Hardware</div>
    <table style="width:100%;border-collapse:collapse;font-size:0.83rem">
        <tr><td style="color:#6B7B6B;padding:2px 0;width:40%">CPU</td>
            <td style="color:#1A1A1A;font-weight:500">{esc((device.get('cpu_model') or '—')[:28])}</td></tr>
        <tr><td style="color:#6B7B6B;padding:2px 0">Cores</td>
            <td style="color:#1A1A1A">{device.get('cpu_cores','?')}</td></tr>
        <tr><td style="color:#6B7B6B;padding:2px 0">RAM</td>
            <td style="color:#1A1A1A">{device.get('ram_gb','?')} GB</td></tr>
        <tr><td style="color:#6B7B6B;padding:2px 0">Agent</td>
            <td style="color:#1A1A1A">v{agent_ver or '?'}{'&nbsp;<span style="background:#F59E0B;color:#FFF;font-size:0.65rem;font-weight:700;padding:1px 5px;border-radius:3px">UPDATE</span>' if update_available else ''}</td></tr>
        <tr><td style="color:#6B7B6B;padding:2px 0">Last seen</td>
            <td style="color:#1A1A1A">{fmt_datetime(device.get('last_seen'))}</td></tr>
    </table>
</div>""", unsafe_allow_html=True)

        with d3:
            fig = go.Figure()
            for val, label, clr in [
                (cpu,  "CPU",  cpu_c),
                (ram,  "RAM",  ram_c),
                (disk, "Disk", disk_c),
            ]:
                fig.add_trace(go.Indicator(
                    mode="gauge+number",
                    value=val,
                    number={"suffix": "%", "font": {"size": 14}},
                    title={"text": label, "font": {"size": 11}},
                    gauge={
                        "axis": {"range": [0, 100], "tickwidth": 1,
                                 "tickcolor": "#DDE8DD", "tickfont": {"size": 9}},
                        "bar":  {"color": clr, "thickness": 0.22},
                        "bgcolor": "#F4F6F4",
                        "borderwidth": 0,
                        "steps": [
                            {"range": [0,  75], "color": "#F4F6F4"},
                            {"range": [75, 90], "color": "#FEF3C7"},
                            {"range": [90,100], "color": "#FEE2E2"},
                        ],
                    },
                    domain={"column": ["cpu", "ram", "disk"].index(label.lower()),
                            "row": 0},
                ))
            fig.update_layout(
                grid={"rows": 1, "columns": 3, "pattern": "independent"},
                height=140, margin=dict(t=20, b=8, l=8, r=8),
                paper_bgcolor="#FFF",
            )
            st.plotly_chart(fig, width='stretch', key=f"gauge_{tab_key}_{device.get('id')}")

        # Assign to customer
        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
        cust_data, cust_err = client.list_customers(per_page=200)
        if cust_err:
            st.caption(f"⚠ Could not load customers — {cust_err}")
        customers = (cust_data or {}).get("items", [])
        cust_options = {c["id"]: c["name"] for c in customers}
        cust_ids = [""] + list(cust_options.keys())
        cust_labels = ["— Unassigned —"] + list(cust_options.values())
        current_cid = device.get("customer_id") or ""
        current_idx = cust_ids.index(current_cid) if current_cid in cust_ids else 0

        ca1, ca2 = st.columns([3, 1])
        with ca1:
            chosen_idx = st.selectbox(
                "Assign to Customer",
                range(len(cust_ids)),
                format_func=lambda x: cust_labels[x],
                index=current_idx,
                key=f"cust_{tab_key}_{device['id']}",
            )
        with ca2:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            if st.button("Save", key=f"save_cust_{tab_key}_{device['id']}"):
                new_cid = cust_ids[chosen_idx] or None
                _, e = client.update_device(device["id"], {"customer_id": new_cid})
                st.error(f"Failed: {e}") if e else st.success(f"Assigned to {cust_labels[chosen_idx]}")
                if not e:
                    st.rerun()

        # Actions
        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
        ab1, ab2, ab3, ab4 = st.columns([1.5, 1, 1, 3])
        with ab1:
            show_hist = st.button("Metrics History", icon=":material/bar_chart:", key=f"hist_{tab_key}_{device['id']}")
        with ab2:
            if is_online and st.button("Reboot", icon=":material/restart_alt:", key=f"reboot_{tab_key}_{device['id']}"):
                _, e = client.reboot_device(device["id"])
                st.error(e) if e else st.success("Reboot queued")
        with ab3:
            if is_online and st.button("Shutdown", icon=":material/power_settings_new:", key=f"shut_{tab_key}_{device['id']}"):
                _, e = client.shutdown_device(device["id"])
                st.error(e) if e else st.success("Shutdown queued")

        if show_hist:
            st.session_state["selected_device_id"] = device["id"]
            mdata, merr = client.get_device_metrics(device["id"], hours=24)
            fallback_hours = None
            if not merr and not mdata:
                # 24h window empty — try 30 days
                mdata, merr = client.get_device_metrics(device["id"], hours=720)
                if mdata:
                    fallback_hours = 720
            if merr or not mdata:
                st.warning("No metric history available.")
            else:
                df = pd.DataFrame(mdata)
                if df.empty:
                    st.info("No metrics recorded yet.")
                else:
                    df["collected_at"] = pd.to_datetime(df["collected_at"])
                    if fallback_hours:
                        oldest = df["collected_at"].min()
                        hours_ago = int((pd.Timestamp.now(tz="UTC") - oldest.tz_convert("UTC")).total_seconds() / 3600)
                        st.info(f"No data in last 24 h — showing last {len(df)} readings (oldest ~{hours_ago}h ago). Agent may be offline.")
                    title_text = "30-day usage history (agent offline)" if fallback_hours else "24-hour usage history"
                    fig2 = px.line(
                        df, x="collected_at",
                        y=["cpu_pct", "ram_pct", "disk_pct"],
                        labels={"value": "Usage %", "collected_at": "Time",
                                "variable": "Metric"},
                        color_discrete_map={
                            "cpu_pct":  "#407E3C",
                            "ram_pct":  "#F59E0B",
                            "disk_pct": "#EF4444",
                        },
                    )
                    fig2.update_traces(line=dict(width=2))
                    plotly_layout(fig2, height=280)
                    fig2.update_layout(
                        paper_bgcolor="#FFF",
                        title=dict(text=title_text,
                                   font=dict(size=12, color="#6B7B6B")),
                    )
                    st.plotly_chart(fig2, width='stretch', key=f"history_{tab_key}_{device.get('id')}")


# ── Render each tab ───────────────────────────────────────────────────────────
def _empty_state(tab_name: str):
    icon_html = {
        "Windows":  '<i class="fa-brands fa-windows"></i>',
        "macOS":    '<i class="fa-brands fa-apple"></i>',
        "Linux":    '<i class="fa-brands fa-linux"></i>',
        "Android":  '<i class="fa-brands fa-android"></i>',
        "iOS":      '<i class="fa-brands fa-apple"></i>',
        "Agentless": '<i class="fa-solid fa-satellite-dish"></i>',
    }.get(tab_name, '<i class="fa-solid fa-desktop"></i>')
    msg = {
        "Agentless": "No agentless devices yet. Run a <b>Network Discovery</b> scan to detect phones and other devices.",
    }.get(tab_name, f"No {tab_name} devices registered. Install and run the agent on a {tab_name} machine.")
    st.markdown(
        f'<div style="text-align:center;padding:2.5rem;background:#FFF;border-radius:12px;'
        f'border:1px solid #DDE8DD;color:#6B7B6B;margin-top:0.5rem">'
        f'<div style="font-size:2rem;margin-bottom:0.5rem">{icon_html}</div>'
        f'<div style="font-size:0.95rem;font-weight:600;color:#1A2B1A;margin-bottom:0.3rem">No devices</div>'
        f'<div style="font-size:0.82rem">{msg}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


for tab, name in zip(tabs, tab_names):
    with tab:
        devices = _tab_devices(name)
        if not devices:
            _empty_state(name)
        else:
            st.markdown(
                f'<div style="font-size:0.8rem;color:#6B7B6B;margin-bottom:0.6rem;padding:0 0.25rem">'
                f'Showing {len(devices)} device{"s" if len(devices) != 1 else ""}</div>',
                unsafe_allow_html=True,
            )
            for device in devices:
                _enrollment = device.get("mdm_enrollment")
                if _enrollment and _enrollment.get("status") == "enrolled":
                    _render_mobile_managed_row(device, tab_key=name)
                elif device.get("is_agentless"):
                    _render_agentless_row(device, tab_key=name)
                else:
                    _render_agent_row(device, tab_key=name, latest_version=_latest_agent_version)

# ── Add Device (manual, agentless — for printers/NAS/routers/anything without an agent) ───
st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)

with st.expander("+ Add Device"):
    st.markdown(
        '<div style="font-size:0.72rem;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;'
        'color:#6B7B6B;margin-bottom:0.75rem">New Device Details — for devices that can\'t run the agent</div>',
        unsafe_allow_html=True,
    )
    _cust_data, _cust_err = client.list_customers(per_page=200)
    if _cust_err:
        st.caption(f"⚠ Could not load customers — {_cust_err}")
    _customers = (_cust_data or {}).get("items", [])
    _cust_options = {c["id"]: c["name"] for c in _customers}
    _add_cust_ids = [""] + list(_cust_options.keys())
    _add_cust_labels = ["— Unassigned —"] + list(_cust_options.values())

    with st.form("add_device_form"):
        af1, af2 = st.columns(2)
        with af1:
            add_hostname = st.text_input("Hostname / Name *", placeholder="e.g. Office Printer")
            add_ip = st.text_input("IP address", placeholder="e.g. 192.168.1.50")
            add_mac = st.text_input("MAC address", placeholder="e.g. AA:BB:CC:DD:EE:FF")
        with af2:
            add_platform = st.selectbox(
                "Platform", ["unknown", "windows", "mac", "linux", "android", "ios"],
            )
            add_dtype = st.selectbox(
                "Device type", ["unknown", "desktop", "laptop", "mobile", "server"],
            )
            add_vendor = st.text_input("Vendor", placeholder="e.g. HP, Netgear")
            add_cust_idx = st.selectbox(
                "Assign to Customer", range(len(_add_cust_ids)),
                format_func=lambda x: _add_cust_labels[x],
            )
        add_submitted = st.form_submit_button("Add Device", width='stretch')

    if add_submitted:
        if not add_hostname.strip():
            st.error("Hostname / name is required.")
        else:
            _, add_err = client.create_device({
                "hostname": add_hostname.strip(),
                "ip_address": add_ip.strip() or None,
                "mac_address": add_mac.strip() or None,
                "platform": add_platform,
                "device_type": add_dtype,
                "vendor": add_vendor.strip() or None,
                "customer_id": _add_cust_ids[add_cust_idx] or None,
            })
            if add_err:
                st.error(f"Failed to add device: {add_err}")
            else:
                st.success(f"Device '{add_hostname.strip()}' added.")
                st.rerun()

_ai_devs = data.get("items", []) if data else []
_ai_online = sum(1 for _d in _ai_devs if _d.get("status") == "online")
render_ai_assistant("Devices", {
    "total_devices": len(_ai_devs),
    "online_devices": _ai_online,
    "offline_devices": len(_ai_devs) - _ai_online,
    "agent_managed": sum(1 for _d in _ai_devs if not _d.get("is_agentless")),
    "agentless_devices": sum(1 for _d in _ai_devs if _d.get("is_agentless")),
})
