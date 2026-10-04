import streamlit as st
from utils.auth import require_auth
from utils.nav import render_sidebar
from utils.ai_assistant import render_ai_assistant
from utils.formatters import fmt_datetime
from utils.styles import inject_css, badge, BRAND, stat_card
from utils.sanitize import esc

st.set_page_config(page_title="OS Patches — RMM", layout="wide")
inject_css()

st.markdown('<h1 style="margin:0">OS Patch Management</h1><p style="color:#6B7B6B;margin:2px 0 1rem;font-size:0.88rem">Windows Update deployment and compliance</p>', unsafe_allow_html=True)

client = require_auth()
render_sidebar()

CARD = "background:#FFFFFF;border-radius:12px;padding:1.2rem 1.5rem;border:1px solid #DDE8DD;box-shadow:0 2px 8px rgba(0,0,0,0.05);margin-bottom:1rem"

# Stat cards row — always visible at top
summary, summary_err = client.get_patch_summary()
if summary_err:
    st.caption(f"⚠ Could not load patch summary — {summary_err}")
elif summary:
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(stat_card("Pending", summary.get("pending", 0), icon="<i class='fa-solid fa-clock'></i>", accent=BRAND["warning"]), unsafe_allow_html=True)
    with c2:
        st.markdown(stat_card("Approved", summary.get("approved", 0), icon="<i class='fa-solid fa-circle-check'></i>", accent=BRAND["info"]), unsafe_allow_html=True)
    with c3:
        st.markdown(stat_card("Deployed", summary.get("deployed", 0), icon="<i class='fa-solid fa-rocket'></i>", accent=BRAND["primary"]), unsafe_allow_html=True)
    with c4:
        compliance = summary.get("compliance_pct", 0)
        compliance_color = BRAND["success"] if compliance >= 90 else (BRAND["warning"] if compliance >= 70 else BRAND["danger"])
        st.markdown(stat_card("Compliance", f"{compliance}%", icon="<i class='fa-solid fa-chart-bar'></i>", accent=compliance_color), unsafe_allow_html=True)
    st.markdown("<div style='margin-bottom:0.5rem'></div>", unsafe_allow_html=True)

# Patch type → color mapping
PATCH_TYPE_COLORS = {
    "critical":   BRAND["danger"],
    "security":   "#F97316",
    "definition": "#3B82F6",
    "rollup":     "#8B5CF6",
    "feature":    BRAND["primary"],
    "driver":     "#6B7B6B",
    "update":     BRAND["info"],
}

def patch_type_badge(patch_type: str) -> str:
    t = (patch_type or "update").lower()
    color = PATCH_TYPE_COLORS.get(t, "#6B7B6B")
    return badge(t, color)

tab1, tab2, tab3 = st.tabs(["Pending Patches", "Patch History", "Policies"])

with tab1:
    pending, err = client.get_pending_patches()
    if err:
        st.error(f"API error: {err}")
    elif not pending:
        st.success("No pending patches — all devices are up to date.")
    else:
        st.markdown(f'<div style="font-size:0.82rem;color:#6B7B6B;margin-bottom:0.75rem">{len(pending)} patch(es) awaiting approval</div>', unsafe_allow_html=True)

        selected_ids = []
        for patch in pending:
            kb = esc(patch.get("kb_id")) or "—"
            ptype = patch.get("patch_type", "update")
            device_label = esc(patch.get("device_hostname") or patch.get("device_id", "")[:8])

            col_chk, col_info = st.columns([0.5, 11])
            with col_chk:
                checked = st.checkbox("", key=f"patch_{patch['id']}", label_visibility="collapsed")
            with col_info:
                row_html = (
                    f'<div style="{CARD};padding:0.75rem 1.1rem;margin-bottom:0.4rem;display:flex;align-items:center;gap:1rem;flex-wrap:wrap">'
                    f'<span style="font-weight:600;font-size:0.9rem;color:#1A1A1A;flex:1;min-width:200px">{esc(patch["patch_name"])}</span>'
                    f'{patch_type_badge(ptype)}'
                    f'<span style="font-size:0.8rem;color:#6B7B6B;white-space:nowrap">KB{kb}</span>'
                    f'<span style="font-size:0.8rem;color:#6B7B6B;white-space:nowrap">Device: <b style="color:#1A1A1A">{device_label}</b></span>'
                    f'</div>'
                )
                st.markdown(row_html, unsafe_allow_html=True)

            if checked:
                selected_ids.append(patch["id"])

        st.markdown("<div style='margin-top:0.5rem'></div>", unsafe_allow_html=True)
        approve_label = f"Approve Selected ({len(selected_ids)})" if selected_ids else "Approve Selected"
        if st.button(approve_label, icon=":material/check_circle:", type="primary", disabled=len(selected_ids) == 0):
            _, approve_err = client.approve_patches(selected_ids)
            if approve_err:
                st.error(approve_err)
            else:
                st.success(f"Approved {len(selected_ids)} patch(es)")
                st.rerun()

with tab2:
    data, err = client.list_patches(per_page=100)
    if err:
        st.error(f"API error: {err}")
    else:
        patches = data.get("items", []) if data else []
        if not patches:
            st.info("No patch history yet.")
        else:
            # Table header
            hdr_style = "background:#1A2B1A;color:#FFFFFF;padding:0.55rem 1rem;font-size:0.75rem;font-weight:700;letter-spacing:0.06em"
            st.markdown(
                f'<div style="border-radius:10px 10px 0 0;overflow:hidden;border:1px solid #DDE8DD">'
                f'<div style="display:grid;grid-template-columns:3fr 1.2fr 1fr 2fr 1.5fr;{hdr_style}">'
                f'<span>PATCH NAME</span><span>TYPE</span><span>STATUS</span><span>DEVICE</span><span>DATE</span>'
                f'</div>',
                unsafe_allow_html=True
            )
            for i, p in enumerate(patches):
                ptype = p.get("patch_type", "update")
                pstatus = p.get("status", "—")
                status_color = {"deployed": BRAND["success"], "approved": BRAND["info"], "pending": BRAND["warning"], "failed": BRAND["danger"]}.get(pstatus.lower(), "#6B7B6B")
                device_label = esc(p.get("device_hostname") or p.get("device_id", "—")[:8])
                date_val = fmt_datetime(p.get("deployed_at") or p.get("created_at"))
                row_bg = "#FFFFFF" if i % 2 == 0 else "#FAFCFA"
                cell_style = f"background:{row_bg};padding:0.6rem 1rem;font-size:0.83rem;border-bottom:1px solid #EEF2EE"
                st.markdown(
                    f'<div style="display:grid;grid-template-columns:3fr 1.2fr 1fr 2fr 1.5fr;{cell_style}">'
                    f'<span style="font-weight:500;color:#1A1A1A;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{esc(p["patch_name"])}</span>'
                    f'<span>{patch_type_badge(ptype)}</span>'
                    f'<span style="color:{status_color};font-weight:600;font-size:0.78rem">{pstatus.upper()}</span>'
                    f'<span style="color:#6B7B6B">{device_label}</span>'
                    f'<span style="color:#6B7B6B">{date_val}</span>'
                    f'</div>',
                    unsafe_allow_html=True
                )
            st.markdown('</div>', unsafe_allow_html=True)

with tab3:
    st.markdown(
        f'<div style="{CARD}">'
        f'<div style="display:flex;align-items:center;gap:0.75rem">'
        f'<span style="font-size:1.5rem"><i class="fa-solid fa-gear"></i></span>'
        f'<div><div style="font-weight:600;color:#1A1A1A;font-size:0.95rem">Patch Policies</div>'
        f'<div style="color:#6B7B6B;font-size:0.83rem;margin-top:2px">Configure granular patch approval policies, maintenance windows, and exclusions via Automation Profiles.</div>'
        f'</div></div>'
        f'</div>',
        unsafe_allow_html=True
    )
    if st.button("Go to Automation Profiles →", key="goto_automation_profiles"):
        st.switch_page("pages/11_Automation.py")
    st.info("Configure patch policies via Automation Profiles")

render_ai_assistant("OS Patches", {"context": "navigation_only"})
