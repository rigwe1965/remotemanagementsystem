"""Remote Terminal — execute shell commands on managed devices."""
import streamlit as st

from utils.auth import require_auth
from utils.nav import render_sidebar
from utils.ai_assistant import render_ai_assistant
from utils.demo import is_simulated, demo_note
from utils.styles import inject_css, BRAND
from utils.sanitize import esc

st.set_page_config(page_title="Terminal — RMM", layout="wide")
inject_css()

client = require_auth()
user = st.session_state.get("user", {})
role = user.get("role", "")

render_sidebar()

if role not in ("admin", "technician", "superadmin"):
    st.error("Remote Terminal is restricted to administrators and technicians.")
    st.stop()

st.markdown(
    '<h1 style="margin:0">Remote Terminal</h1>'
    '<p style="color:#6B7B6B;margin:2px 0 1rem;font-size:0.88rem">'
    'Execute shell commands on managed devices — all commands are audit-logged</p>',
    unsafe_allow_html=True,
)

# ── Load online agent-managed devices ────────────────────────────────────────
dev_data, dev_err = client.list_devices(per_page=200)
devices = (dev_data.get("items", []) if dev_data else [])
online_agents = [
    d for d in devices
    if not d.get("is_agentless") and d.get("is_online") and d.get("status") != "offline"
]

if not online_agents:
    st.info("No reachable agent-managed devices found. Devices must have an active agent to open a terminal session.")
    st.stop()

# ── Session state init ────────────────────────────────────────────────────────
if "_term_session_id" not in st.session_state:
    st.session_state["_term_session_id"] = None
if "_term_device_id" not in st.session_state:
    st.session_state["_term_device_id"] = None
if "_term_output_seq" not in st.session_state:
    st.session_state["_term_output_seq"] = 0
if "_term_output_buf" not in st.session_state:
    st.session_state["_term_output_buf"] = []
if "_term_pending_cmd" not in st.session_state:
    st.session_state["_term_pending_cmd"] = ""

session_id = st.session_state["_term_session_id"]

# ── Device selector + connect/disconnect ──────────────────────────────────────
dev_map = {f"{d.get('hostname') or d['id']} ({d.get('platform','')})": d["id"] for d in online_agents}
simulated_device_ids = {d["id"] for d in online_agents if is_simulated(d)}
# A hosted-demo device has no agent, so a real session would wait forever. For those the session lives only in this page's state:
# it "connects", echoes what is typed, and answers with a plain explanation. Nothing is sent to the API.
DEMO_SESSION = "demo-simulated-session"

top_l, top_r = st.columns([3, 1])
with top_l:
    if session_id:
        connected_hostname = next(
            (d.get("hostname") or d["id"] for d in online_agents if d["id"] == st.session_state["_term_device_id"]),
            st.session_state["_term_device_id"],
        )
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:10px;padding:0.5rem 0">'
            f'<span style="width:10px;height:10px;border-radius:50%;background:#22C55E;display:inline-block"></span>'
            f'<span style="font-weight:600;color:#1A1A1A">Connected to {esc(connected_hostname)}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        chosen_label = st.selectbox("Select device", list(dev_map.keys()), key="_term_dev_sel")

with top_r:
    if session_id:
        if st.button("Disconnect", type="secondary", width='stretch'):
            if session_id != DEMO_SESSION:
                client.close_terminal_session(session_id)
            st.session_state["_term_session_id"] = None
            st.session_state["_term_device_id"] = None
            st.session_state["_term_output_seq"] = 0
            st.session_state["_term_output_buf"] = []
            st.rerun()
    else:
        if st.button("Connect", type="primary", width='stretch'):
            device_id = dev_map[chosen_label]
            if device_id in simulated_device_ids:
                st.session_state["_term_session_id"] = DEMO_SESSION
                st.session_state["_term_device_id"] = device_id
                st.session_state["_term_output_seq"] = 0
                st.session_state["_term_output_buf"] = [{
                    "content": f"Connected to {chosen_label.split(' (')[0]} (demo). " + demo_note("run commands") + "\r\n",
                    "stream": "system",
                }]
                st.rerun()
            data, err = client.create_terminal_session(device_id)
            if err:
                st.error(f"Could not open session: {err}")
            else:
                st.session_state["_term_session_id"] = data["id"]
                st.session_state["_term_device_id"] = device_id
                st.session_state["_term_output_seq"] = 0
                st.session_state["_term_output_buf"] = []
                st.rerun()

st.markdown("<hr style='margin:0.4rem 0;border-color:#DDE8DD'>", unsafe_allow_html=True)

if not session_id:
    st.markdown(
        '<div style="text-align:center;padding:4rem 2rem;background:#FFFFFF;border-radius:12px;'
        'border:1px solid #DDE8DD;color:#6B7B6B;margin-top:1rem">'
        '<div style="font-size:2rem;margin-bottom:0.75rem">⌨️</div>'
        '<div style="font-size:1rem;font-weight:600;color:#1A2B1A;margin-bottom:0.4rem">No active session</div>'
        '<div style="font-size:0.85rem">Select a device above and click Connect to open a remote terminal.</div>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.stop()

def _render_content(content: str) -> str:
    return (
        content
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )


@st.fragment(run_every=2)
def _output_panel():
    sid = st.session_state.get("_term_session_id")
    if not sid:
        return
    if sid == DEMO_SESSION:
        poll_data, poll_err = {"session": {}, "output": [], "pending_commands": 0}, None
    else:
        poll_data, poll_err = client.get_terminal_output(sid, after=st.session_state["_term_output_seq"])
    if poll_err:
        st.error(f"Session error: {poll_err}")
        st.session_state["_term_session_id"] = None
        st.rerun()
        return

    session_info = poll_data.get("session", {})
    new_chunks = poll_data.get("output", [])
    pending_commands = poll_data.get("pending_commands", 0)

    if new_chunks:
        for chunk in new_chunks:
            st.session_state["_term_output_buf"].append(chunk)
        st.session_state["_term_output_seq"] = new_chunks[-1]["id"]
        if len(st.session_state["_term_output_buf"]) > 500:
            st.session_state["_term_output_buf"] = st.session_state["_term_output_buf"][-500:]

    if session_info.get("status") == "closed":
        st.session_state["_term_output_buf"].append({
            "content": "\r\n[Session closed]\r\n",
            "stream": "system",
        })
        st.session_state["_term_session_id"] = None
        st.session_state["_term_output_seq"] = 0

    output_html_parts = []
    for chunk in st.session_state["_term_output_buf"]:
        stream = chunk.get("stream", "stdout")
        text = _render_content(chunk.get("content", ""))
        color = "#FF6B6B" if stream == "stderr" else "#94A3B8" if stream == "system" else "#E2E8F0"
        output_html_parts.append(f'<span style="color:{color}">{text}</span>')

    if pending_commands > 0:
        output_html_parts.append(
            '<span style="color:#F59E0B">&#9650; waiting for agent to execute command'
            ' <span class="term-blink">▋</span></span>'
        )

    output_html = "".join(output_html_parts) or '<span style="color:#94A3B8">Waiting for output...</span>'
    st.markdown(
        '<style>'
        '@keyframes blink{0%,100%{opacity:1}50%{opacity:0}}'
        '.term-blink{animation:blink 1s step-start infinite}'
        '</style>'
        f'<div id="term-output" style="'
        f'background:#0D1117;border-radius:8px;padding:1rem;'
        f'font-family:Consolas,monospace;font-size:0.82rem;'
        f'height:420px;overflow-y:auto;white-space:pre-wrap;'
        f'border:1px solid #2D3748;line-height:1.5">'
        f'{output_html}'
        f'</div>'
        f'<script>var t=document.getElementById("term-output");if(t)t.scrollTop=t.scrollHeight;</script>',
        unsafe_allow_html=True,
    )


_output_panel()

# ── Command input ─────────────────────────────────────────────────────────────
st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

cmd_col, send_col = st.columns([5, 1])
with cmd_col:
    command = st.text_input(
        "Command",
        key="_term_cmd_input",
        placeholder="Enter shell command (e.g. dir, ipconfig, whoami)",
        label_visibility="collapsed",
    )
with send_col:
    send_clicked = st.button("Send ▶", type="primary", width='stretch')

if send_clicked and command.strip() and session_id == DEMO_SESSION:
    st.session_state["_term_output_buf"] += [
        {"content": f"$ {command.strip()}\r\n", "stream": "stdout"},
        {"content": "Not run: " + demo_note("run it") + "\r\n", "stream": "system"},
    ]
    st.rerun()
elif send_clicked and command.strip():
    _, err = client.send_terminal_command(session_id, command.strip())
    if err:
        st.error(f"Failed to send command: {err}")
    else:
        st.session_state["_term_pending_cmd"] = command.strip()
        st.rerun()

# ── Legend ────────────────────────────────────────────────────────────────────
st.markdown(
    '<div style="margin-top:0.5rem;font-size:0.75rem;color:#6B7B6B;display:flex;gap:1.5rem">'
    '<span><span style="color:#E2E8F0">■</span> stdout</span>'
    '<span><span style="color:#FF6B6B">■</span> stderr</span>'
    '<span><span style="color:#94A3B8">■</span> system</span>'
    '<span style="margin-left:auto">Auto-refresh every 2s while connected — all commands audit-logged</span>'
    '</div>',
    unsafe_allow_html=True,
)

render_ai_assistant("Remote Terminal", {"context": "navigation_only"})
