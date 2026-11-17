"""Maintenance — Device maintenance and remote actions."""
import streamlit as st

from utils.auth import require_auth
from utils.nav import render_sidebar
from utils.ai_assistant import render_ai_assistant
from utils.demo import is_simulated, demo_note
from utils.styles import inject_css, badge, BRAND, stat_card
from utils.formatters import fmt_datetime, fmt_bytes
from utils.sanitize import esc

st.set_page_config(page_title="Maintenance — RMM", layout="wide")
inject_css()

client = require_auth()
render_sidebar()

st.markdown('<h1 style="margin:0">Maintenance</h1><p style="color:#6B7B6B;margin:2px 0 1rem;font-size:0.88rem">Device maintenance and remote actions</p>', unsafe_allow_html=True)

# ── Load online devices ───────────────────────────────────────────────────────
with st.spinner("Loading devices..."):
    data, err = client.list_devices(per_page=200)
if err:
    st.warning(f"Could not load devices — {err}")
    st.stop()

all_devices = data.get("items", [])
online_devices = [d for d in all_devices if d.get("is_online")]

if not online_devices:
    st.markdown(
        '<div style="text-align:center;padding:3rem;background:#FFFFFF;border-radius:12px;'
        'border:1px solid #DDE8DD;color:#6B7B6B">'
        '<div style="font-size:2rem;margin-bottom:0.75rem"><i class="fa-solid fa-wrench" style="color:#6B7B6B"></i></div>'
        '<div style="font-size:1rem;font-weight:600;color:#1A2B1A;margin-bottom:0.4rem">No online devices</div>'
        '<div style="font-size:0.85rem">At least one device must be online to perform maintenance actions.</div>'
        '</div>',
        unsafe_allow_html=True
    )
    st.stop()

# ── Device selector ───────────────────────────────────────────────────────────
def _device_label(d):
    return f"{d['hostname']}  ({d.get('ip_address', '—')})"

device_options = {_device_label(d): d for d in online_devices}
sel_col, _ = st.columns([2.5, 3.5])
with sel_col:
    chosen_label = st.selectbox("Select Device", list(device_options.keys()))

selected = device_options[chosen_label]

# ── Device info card ──────────────────────────────────────────────────────────
metrics = selected.get("latest_metrics") or {}
uptime_sec = metrics.get("uptime_seconds")

def _fmt_uptime(seconds):
    if not seconds:
        return "—"
    d, rem = divmod(int(seconds), 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    return " ".join(parts) or "< 1m"

os_str = esc(f"{selected.get('os_name') or '—'} {selected.get('os_version') or ''}".strip())

st.markdown(
    f'<div style="background:#FFFFFF;border-radius:12px;padding:1.1rem 1.5rem;'
    f'border:1px solid #DDE8DD;box-shadow:0 2px 8px rgba(0,0,0,0.05);margin-bottom:1.25rem">'
    f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:0.6rem">'
    f'<div style="width:10px;height:10px;border-radius:50%;background:#22C55E;box-shadow:0 0 6px #22C55E88;flex-shrink:0"></div>'
    f'<span style="font-size:1rem;font-weight:700;color:#1A1A1A">{esc(selected.get("hostname","—"))}</span>'
    f'<span style="font-size:0.8rem;color:#6B7B6B">{esc(selected.get("ip_address","—"))}</span>'
    f'</div>'
    f'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:1rem;font-size:0.82rem">'
    f'<div><span style="color:#6B7B6B">OS</span><br><b style="color:#1A1A1A">{os_str or "—"}</b></div>'
    f'<div><span style="color:#6B7B6B">Platform</span><br><b style="color:#1A1A1A">{esc(selected.get("platform","—"))}</b></div>'
    f'<div><span style="color:#6B7B6B">Last Seen</span><br><b style="color:#1A1A1A">{fmt_datetime(selected.get("last_seen",""))}</b></div>'
    f'<div><span style="color:#6B7B6B">Uptime</span><br><b style="color:#1A1A1A">{_fmt_uptime(uptime_sec)}</b></div>'
    f'</div></div>',
    unsafe_allow_html=True
)

# ── Action grid ───────────────────────────────────────────────────────────────
st.markdown(
    '<div style="font-size:0.75rem;font-weight:700;text-transform:uppercase;'
    'letter-spacing:0.07em;color:#6B7B6B;margin-bottom:0.6rem">Actions</div>',
    unsafe_allow_html=True
)

# Confirmation gate for destructive actions
confirm_key = f"maint_confirm_{selected['id']}"
confirm_state_key = f"maint_confirm_state_{selected['id']}"
if confirm_state_key not in st.session_state:
    st.session_state[confirm_state_key] = False

confirm_checked = st.checkbox(
    "I confirm this action on the selected device",
    key=confirm_key,
    value=st.session_state[confirm_state_key],
)

st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

# Row 1
r1c1, r1c2, r1c3 = st.columns(3)
with r1c1:
    reboot_btn = st.button("Reboot", icon=":material/restart_alt:", width='stretch', key=f"reboot_{selected['id']}")
with r1c2:
    shutdown_btn = st.button("Shutdown", icon=":material/power_settings_new:", width='stretch', key=f"shut_{selected['id']}")
with r1c3:
    restore_btn = st.button("Create Restore Point", icon=":material/backup:", width='stretch', key=f"restore_{selected['id']}")

# Row 2
r2c1, r2c2, r2c3 = st.columns(3)
with r2c1:
    temp_btn = st.button("Delete Temp Files", icon=":material/delete_sweep:", width='stretch', key=f"temp_{selected['id']}")
with r2c2:
    browser_btn = st.button("Clear Browser History", icon=":material/public:", width='stretch', key=f"browser_{selected['id']}")
with r2c3:
    chkdsk_btn = st.button("Check Disk", icon=":material/health_and_safety:", width='stretch', key=f"chkdsk_{selected['id']}")

# ── Action handlers ───────────────────────────────────────────────────────────
if reboot_btn:
    if not confirm_checked:
        st.warning("Check the confirmation box above before rebooting.")
    elif is_simulated(selected):
        st.info(demo_note("reboot"))
    else:
        with st.spinner(f"Sending reboot command to {selected['hostname']}..."):
            _, action_err = client.reboot_device(selected["id"])
        if action_err:
            st.error(f"Reboot failed: {action_err}")
        else:
            st.success(f"Reboot command sent to {selected['hostname']}.")
            st.session_state[confirm_state_key] = False

if shutdown_btn:
    if not confirm_checked:
        st.warning("Check the confirmation box above before shutting down.")
    elif is_simulated(selected):
        st.info(demo_note("shut down"))
    else:
        with st.spinner(f"Sending shutdown command to {selected['hostname']}..."):
            _, action_err = client.shutdown_device(selected["id"])
        if action_err:
            st.error(f"Shutdown failed: {action_err}")
        else:
            st.success(f"Shutdown command sent to {selected['hostname']}.")
            st.session_state[confirm_state_key] = False

def _queue(task_type: str, label: str):
    if not confirm_checked:
        st.warning("Check the confirmation box above before running this action.")
        return
    if is_simulated(selected):
        st.info(demo_note(f"run \"{label}\""))
        return
    with st.spinner(f"Queuing {label}..."):
        _, err = client.queue_device_task(selected["id"], task_type)
    if err:
        st.error(f"Failed to queue {label}: {err}")
    else:
        st.success(f"{label} queued. Agent will execute on next poll.")
        st.session_state[confirm_state_key] = False

if restore_btn:
    _queue("restore_point", "Create Restore Point")

if temp_btn:
    _queue("clean_temp", "Delete Temp Files")

if browser_btn:
    _queue("clear_browser", "Clear Browser History")

if chkdsk_btn:
    _queue("check_disk", "Check Disk")

# ── Maintenance log ───────────────────────────────────────────────────────────
st.markdown("<div style='height:1.25rem'></div>", unsafe_allow_html=True)
st.markdown(
    '<div style="font-size:0.75rem;font-weight:700;text-transform:uppercase;'
    'letter-spacing:0.07em;color:#6B7B6B;margin-bottom:0.6rem">Recent Maintenance Runs</div>',
    unsafe_allow_html=True
)

runs_data, runs_err = client._get("/api/automation/runs")
if runs_err or not runs_data:
    st.markdown(
        '<div style="background:#FFFFFF;border-radius:10px;padding:1rem 1.25rem;'
        'border:1px solid #DDE8DD;font-size:0.83rem;color:#6B7B6B">'
        'No maintenance run history available. Scheduled task runs will appear here once automation profiles are configured.'
        '</div>',
        unsafe_allow_html=True
    )
else:
    runs = runs_data if isinstance(runs_data, list) else runs_data.get("items", [])
    if not runs:
        st.markdown(
            '<div style="background:#FFFFFF;border-radius:10px;padding:1rem 1.25rem;'
            'border:1px solid #DDE8DD;font-size:0.83rem;color:#6B7B6B">'
            'No maintenance runs recorded yet.'
            '</div>',
            unsafe_allow_html=True
        )
    else:
        STATUS_COLORS_RUN = {
            "success":  BRAND["success"],
            "failed":   BRAND["danger"],
            "running":  BRAND["warning"],
            "pending":  BRAND["muted"],
        }

        # Bulk action toolbar
        queued_count = sum(1 for r in runs if (r.get("status") or "").lower() == "queued")
        tool_col1, tool_col2 = st.columns([6, 1])
        with tool_col2:
            if queued_count > 0:
                if st.button(f"Clear {queued_count} Queued", icon=":material/delete:", key="clear_queued", type="secondary"):
                    _, cerr = client.clear_queued_runs()
                    if cerr:
                        st.error(f"Failed: {cerr}")
                    else:
                        st.success(f"Cleared {queued_count} queued run(s).")
                        st.rerun()

        # Table header
        h0, h1, h2, h3, h4, h5 = st.columns([2, 2, 1.5, 1.5, 1, 0.5])
        for col, label in zip([h0, h1, h2, h3, h4, h5],
                               ["Profile", "Device", "Started", "Finished", "Status", ""]):
            col.markdown(
                f"<div style='font-size:0.72rem;font-weight:700;text-transform:uppercase;"
                f"letter-spacing:0.07em;color:#6B7B6B;padding:0.3rem 0'>{label}</div>",
                unsafe_allow_html=True,
            )
        st.divider()

        for i, run in enumerate(runs[:50]):
            status_raw = (run.get("status") or "unknown").lower()
            run_color  = STATUS_COLORS_RUN.get(status_raw, BRAND["muted"])
            profile_name = esc(run.get("profile_name") or run.get("profile_id", "")[:8] or "—")
            device_name  = esc(run.get("device_hostname") or run.get("device_id", "")[:8] or "—")
            started  = fmt_datetime(run.get("started_at") or "")
            finished = fmt_datetime(run.get("finished_at") or "")

            c0, c1, c2, c3, c4, c5 = st.columns([2, 2, 1.5, 1.5, 1, 0.5])
            c0.markdown(f"<div style='font-size:0.83rem;font-weight:500;color:#1A1A1A'>{profile_name}</div>", unsafe_allow_html=True)
            c1.markdown(f"<div style='font-size:0.83rem;color:#4A5A4A'>{device_name}</div>", unsafe_allow_html=True)
            c2.markdown(f"<div style='font-size:0.78rem;color:#6B7B6B'>{started}</div>", unsafe_allow_html=True)
            c3.markdown(f"<div style='font-size:0.78rem;color:#6B7B6B'>{finished}</div>", unsafe_allow_html=True)
            c4.markdown(badge(status_raw, run_color), unsafe_allow_html=True)
            if c5.button("✕", key=f"del_run_{run['id']}_{i}", help="Delete this run"):
                _, derr = client.delete_run(run["id"])
                if derr:
                    st.error(f"Failed: {derr}")
                else:
                    st.rerun()

render_ai_assistant("Maintenance", {"context": "navigation_only"})
