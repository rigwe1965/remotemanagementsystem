import streamlit as st
from utils.auth import require_auth
from utils.nav import render_sidebar
from utils.ai_assistant import render_ai_assistant
from utils.demo import is_simulated, demo_note
from utils.formatters import fmt_datetime
from utils.styles import inject_css, badge, BRAND, stat_card
from utils.sanitize import esc

st.set_page_config(page_title="Scripts — RMM", layout="wide")
inject_css()

st.markdown('<h1 style="margin:0">Scripts</h1><p style="color:#6B7B6B;margin:2px 0 1rem;font-size:0.88rem">Script library and execution</p>', unsafe_allow_html=True)

client = require_auth()
render_sidebar()

CARD = "background:#FFFFFF;border-radius:12px;padding:1.2rem 1.5rem;border:1px solid #DDE8DD;box-shadow:0 2px 8px rgba(0,0,0,0.05);margin-bottom:1rem"

# Script type → badge color
FTYPE_COLORS = {
    "ps1": "#3B82F6",
    "bat": "#F97316",
    "py":  BRAND["primary"],
    "sh":  "#8B5CF6",
}

def ftype_badge(file_type: str) -> str:
    ft = (file_type or "").lower()
    color = FTYPE_COLORS.get(ft, "#6B7B6B")
    return badge(ft, color)

tab1, tab2, tab3 = st.tabs(["Library", "Upload", "Run History"])

with tab1:
    data, err = client.list_scripts()
    if err:
        st.error(f"API error: {err}")
    else:
        scripts = data or []

        # Load online devices once
        dev_data, _ = client.list_devices(per_page=200)
        devices = dev_data.get("items", []) if dev_data else []
        device_options = {d["hostname"]: d["id"] for d in devices if d.get("is_online")}
        simulated_ids = {d["id"] for d in devices if is_simulated(d)}   # hosted-demo devices: no agent to run a script

        # Search filter
        search = st.text_input("Search scripts", placeholder="Filter by name or description…", label_visibility="visible")
        if search:
            q = search.lower()
            scripts = [s for s in scripts if q in s["name"].lower() or q in (s.get("description") or "").lower()]

        st.markdown(f'<div style="font-size:0.82rem;color:#6B7B6B;margin-bottom:0.5rem">{len(scripts)} script(s)</div>', unsafe_allow_html=True)

        if not scripts:
            st.info("No scripts found.")
        else:
            for script in scripts:
                ft = script.get("file_type", "").lower()
                tag = "[Built-in]" if script.get("is_builtin") else "[Custom]"
                ft_badge_html = ftype_badge(ft)
                expander_label = f'{tag}  {script["name"]}  [{ft.upper()}]'

                with st.expander(expander_label):
                    # Meta row
                    meta_html = (
                        f'<div style="display:flex;align-items:center;gap:0.75rem;flex-wrap:wrap;margin-bottom:0.75rem">'
                        f'{ft_badge_html}'
                        f'<span style="font-size:0.82rem;color:#6B7B6B">OS: <b style="color:#1A1A1A">{esc(script.get("os_target","—"))}</b></span>'
                        f'<span style="font-size:0.82rem;color:#6B7B6B">Created: <b style="color:#1A1A1A">{fmt_datetime(script.get("created_at",""))}</b></span>'
                        f'</div>'
                    )
                    st.markdown(meta_html, unsafe_allow_html=True)

                    desc = esc(script.get("description")).replace("\n", "<br>") or "—"
                    st.markdown(f'<div style="font-size:0.88rem;color:#1A1A1A;margin-bottom:0.75rem"><b>Description:</b> {desc}</div>', unsafe_allow_html=True)

                    # Device selector + run controls
                    col_dev, col_to, col_run = st.columns([4, 2, 1])
                    with col_dev:
                        selected_devs = st.multiselect(
                            "Run on online devices",
                            list(device_options.keys()),
                            key=f"devs_{script['id']}"
                        )
                    with col_to:
                        timeout = st.number_input("Timeout (s)", 10, 900, 300, key=f"to_{script['id']}")
                    with col_run:
                        st.markdown("<div style='margin-top:1.75rem'></div>", unsafe_allow_html=True)
                        if st.button("Run", icon=":material/play_arrow:", key=f"run_{script['id']}"):
                            if not selected_devs:
                                st.warning("Select at least one device")
                            else:
                                device_ids = [device_options[d] for d in selected_devs]
                                real_ids = [i for i in device_ids if i not in simulated_ids]
                                if len(real_ids) < len(device_ids):
                                    st.info(demo_note("run a script"))
                                if real_ids:
                                    result, run_err = client.run_script(script["id"], real_ids, timeout)
                                    if run_err:
                                        st.error(f"Failed: {run_err}")
                                    else:
                                        st.success(f"Queued on {result.get('queued', 0)} device(s)")

                    # Script content preview (collapsed)
                    if script.get("content"):
                        with st.expander("View script content", expanded=False):
                            st.code(script["content"], language=ft if ft in ("python", "ps1", "bat", "sh") else "text")

with tab2:
    st.markdown(f'<div style="{CARD}"><div style="font-weight:700;font-size:1rem;color:#1A1A1A;margin-bottom:1rem">Upload New Script</div>', unsafe_allow_html=True)
    with st.form("upload_script"):
        col_name, col_type = st.columns([3, 1])
        with col_name:
            s_name = st.text_input("Script Name *", placeholder="e.g. Clear Temp Files")
        with col_type:
            s_type = st.selectbox("Type", ["ps1", "bat", "py", "sh"])
        s_desc = st.text_area("Description", placeholder="What does this script do?", height=80)
        s_content = st.text_area(
            "Script Content *",
            height=300,
            placeholder="Write your script here…"
        )
        submitted = st.form_submit_button("Upload Script", type="primary")
    st.markdown("</div>", unsafe_allow_html=True)

    if submitted:
        if not s_name or not s_content:
            st.error("Name and content are required")
        else:
            _, up_err = client.create_script({
                "name": s_name,
                "description": s_desc,
                "file_type": s_type,
                "content": s_content,
            })
            if up_err:
                st.error(f"Failed: {up_err}")
            else:
                st.success("Script uploaded!")
                st.rerun()

with tab3:
    runs_data, err = client.list_script_runs(per_page=50)
    if err:
        st.error(f"API error: {err}")
    else:
        runs = runs_data.get("items", []) if runs_data else []
        if not runs:
            st.info("No script runs yet.")
        else:
            STATUS_ICONS = {
                "success": "[OK]",
                "failed":  "[FAIL]",
                "queued":  "[QUEUE]",
                "running": "[RUN]",
                "timeout": "[TIMEOUT]",
            }
            STATUS_COLORS_RUN = {
                "success": BRAND["success"],
                "failed":  BRAND["danger"],
                "queued":  BRAND["warning"],
                "running": BRAND["info"],
                "timeout": "#8B5CF6",
            }
            for run in runs:
                status = run.get("status", "queued")
                icon = STATUS_ICONS.get(status, "[?]")
                status_color = STATUS_COLORS_RUN.get(status, "#6B7B6B")
                script_name = run.get("script_name") or f'script:{run.get("script_id","")[:8]}'
                hostname = run.get("device_hostname") or run.get("device_id", "")[:8]
                # Truncate hostname to 20 chars
                hostname_display = hostname[:20] + "…" if len(hostname) > 20 else hostname
                triggered = fmt_datetime(run.get("triggered_at", ""))

                # Duration calculation
                started = run.get("started_at")
                completed = run.get("completed_at")
                if started and completed:
                    try:
                        from datetime import datetime as _dt
                        s = _dt.fromisoformat(started.replace("Z", "+00:00"))
                        e = _dt.fromisoformat(completed.replace("Z", "+00:00"))
                        secs = int((e - s).total_seconds())
                        duration = f"{secs}s"
                    except Exception:
                        duration = "—"
                else:
                    duration = "—"

                expander_label = f'{icon} {script_name}  ·  {hostname_display}  ·  {status.upper()}  ·  {triggered}'
                with st.expander(expander_label):
                    # Summary row
                    summary_html = (
                        f'<div style="display:flex;gap:1.5rem;flex-wrap:wrap;margin-bottom:0.75rem">'
                        f'<span style="font-size:0.82rem;color:#6B7B6B">Status: <b style="color:{status_color}">{status.upper()}</b></span>'
                        f'<span style="font-size:0.82rem;color:#6B7B6B">Device: <b style="color:#1A1A1A">{esc(hostname)}</b></span>'
                        f'<span style="font-size:0.82rem;color:#6B7B6B">Duration: <b style="color:#1A1A1A">{duration}</b></span>'
                        f'<span style="font-size:0.82rem;color:#6B7B6B">Exit code: <b style="color:#1A1A1A">{run.get("exit_code", "—")}</b></span>'
                        f'<span style="font-size:0.82rem;color:#6B7B6B">Started: <b style="color:#1A1A1A">{fmt_datetime(started)}</b></span>'
                        f'<span style="font-size:0.82rem;color:#6B7B6B">Completed: <b style="color:#1A1A1A">{fmt_datetime(completed)}</b></span>'
                        f'</div>'
                    )
                    st.markdown(summary_html, unsafe_allow_html=True)

                    if run.get("stdout"):
                        st.markdown('<span style="font-size:0.82rem;font-weight:600;color:#1A1A1A">stdout</span>', unsafe_allow_html=True)
                        st.code(run["stdout"], language="text")
                    if run.get("stderr"):
                        st.markdown('<span style="font-size:0.82rem;font-weight:600;color:#EF4444">stderr</span>', unsafe_allow_html=True)
                        st.code(run["stderr"], language="text")
                    if not run.get("stdout") and not run.get("stderr"):
                        st.caption("No output captured.")

render_ai_assistant("Scripts", {"context": "navigation_only"})
