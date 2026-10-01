"""Shared sidebar navigation — call on every page after require_auth()."""
import streamlit as st
from utils.auth import current_user, logout
from utils.sanitize import esc


def render_sidebar() -> None:
    import base64 as _b64
    user = current_user() or {}
    role = user.get("role", "")
    branding = st.session_state.get("_branding", {})
    app_name  = branding.get("app_name", "RMM System")
    logo_data = branding.get("logo_data")

    with st.sidebar:
        # ── Brand header ──────────────────────────────────────────────────────
        if logo_data:
            try:
                _, b64_part = logo_data.split(",", 1)
                img_bytes = _b64.b64decode(b64_part)
                st.image(img_bytes, width=120)
            except Exception:
                st.markdown(
                    f'<div style="padding:0.9rem 1rem 0.5rem;font-weight:700;font-size:1rem;color:#E0F0E0">'
                    f'{esc(app_name)}</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(
                f'<div style="padding:0.9rem 1rem 0.5rem;font-weight:700;font-size:1rem;color:#E0F0E0">'
                f'{esc(app_name)}</div>',
                unsafe_allow_html=True,
            )

        # ── User card ─────────────────────────────────────────────────────────
        _role_pill = {
            "superadmin": ("#7C3AED", "#7C3AED15"),
            "admin":      ("#EF4444", "#EF444415"),
            "technician": ("#F59E0B", "#F59E0B15"),
            "viewer":     ("#22C55E", "#22C55E15"),
        }
        rc, rb = _role_pill.get(role, ("#8492A6", "#8492A615"))
        name   = user.get("full_name") or user.get("email", "User")
        avatar = name[0].upper()

        st.markdown(f"""
        <div style="padding:1.1rem 1rem 0.9rem;border-bottom:1px solid #1A2E1A;margin-bottom:0.5rem">
            <div style="display:flex;align-items:center;gap:10px">
                <div style="width:38px;height:38px;border-radius:50%;flex-shrink:0;
                            background:linear-gradient(135deg,#2D5C29,#5DB85A);
                            display:flex;align-items:center;justify-content:center;
                            color:#FFF;font-weight:700;font-size:0.9rem;
                            box-shadow:0 2px 8px rgba(64,126,60,0.4)">{avatar}</div>
                <div style="min-width:0">
                    <div style="color:#FFFFFF;font-weight:600;font-size:0.86rem;
                                white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
                        {esc(name)}</div>
                    <span style="background:{rb};color:{rc};padding:2px 8px;border-radius:20px;
                                 font-size:0.65rem;font-weight:700;display:inline-block;margin-top:2px">
                        {role.upper()}</span>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # ── Admin shortcut (top, admin only) ─────────────────────────────────
        if role in ("admin", "superadmin"):
            if st.button("Admin Panel", width='stretch', key="nav_admin", icon=":material/admin_panel_settings:"):
                st.switch_page("pages/10_Admin.py")
            st.markdown("<div style='height:0.25rem'></div>", unsafe_allow_html=True)

        # ── Nav sections ──────────────────────────────────────────────────────
        def nav_section(label: str, first: bool = False):
            divider = (
                "" if first else
                '<div style="border-top:1px solid #1E3320;margin:0.35rem 0.5rem 0"></div>'
            )
            st.markdown(
                f'{divider}'
                f'<div style="display:flex;align-items:center;gap:7px;padding:0.75rem 0.75rem 0.2rem">'
                f'<div style="width:3px;height:13px;background:#407E3C;border-radius:2px;flex-shrink:0"></div>'
                f'<span style="color:#7EC87E;font-size:0.68rem;font-weight:700;letter-spacing:0.1em">{label}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

        nav_section("MONITORING", first=True)
        st.page_link("pages/01_Dashboard.py",        label="Overview",          icon=":material/bar_chart:")
        st.page_link("pages/04_Devices.py",          label="Devices",           icon=":material/computer:")
        st.page_link("pages/05_Alerts.py",           label="Alerts",            icon=":material/notifications:")

        nav_section("MANAGEMENT")
        st.page_link("pages/02_Tickets.py",          label="Tickets",           icon=":material/confirmation_number:")
        st.page_link("pages/03_Customers.py",        label="Customers",         icon=":material/groups:")
        st.page_link("pages/11_Automation.py",       label="Automation",        icon=":material/smart_toy:")

        nav_section("PATCHING")
        st.page_link("pages/12_OS_Patches.py",       label="OS Patches",        icon=":material/system_update:")
        st.page_link("pages/13_Software_Patches.py", label="Software Patches",  icon=":material/inventory_2:")

        nav_section("TOOLS")
        st.page_link("pages/16_Scripts.py",          label="Scripts",           icon=":material/code:")
        if role in ("admin", "technician", "superadmin"):
            st.page_link("pages/14_Terminal.py",     label="Remote Terminal",   icon=":material/terminal:")
        st.page_link("pages/14_Disk_Management.py",  label="Disk Management",   icon=":material/storage:")
        st.page_link("pages/15_Maintenance.py",      label="Maintenance",       icon=":material/build:")
        st.page_link("pages/07_Network_Discovery.py",label="Network Discovery", icon=":material/wifi_find:")
        st.page_link("pages/18_IoT_Sensors.py",      label="IoT Sensors",       icon=":material/sensors:")
        if role in ("admin", "superadmin", "technician"):
            st.page_link("pages/19_Mobile_Enrollment.py", label="Mobile Enrollment", icon=":material/phone_iphone:")

        if role in ("admin", "superadmin", "technician"):
            nav_section("BUSINESS")
            st.page_link("pages/08_Reports.py",      label="Reports",           icon=":material/bar_chart:")
            st.page_link("pages/09_Billing.py",      label="Billing",           icon=":material/payments:")

        if role in ("admin", "superadmin"):
            nav_section("USAGE")
            st.page_link("pages/22_Usage_Monitoring.py", label="Usage Monitoring", icon=":material/monitoring:")

        nav_section("ACCOUNT")
        st.page_link("pages/17_Profile.py", label="My Profile", icon=":material/person:")

        st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)
        if st.button("Sign Out", width='stretch', key="sidebar_signout", icon=":material/logout:"):
            logout()
