"""
RMM Dashboard — Streamlit entrypoint & login page.
"""
import os
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Load branding before set_page_config (no session_state yet at this point)
from utils.branding import fetch_branding_early
_brand_early = fetch_branding_early()

st.set_page_config(
    page_title=_brand_early.get("app_name", "RMM System"),
    page_icon=":material/computer:",
    layout="wide",
    initial_sidebar_state="expanded",
)

from utils.styles import inject_css, stat_card, BRAND
from utils.branding import load_branding

# Cache branding into session_state for all pages to use
load_branding()
inject_css()

# ── Login ─────────────────────────────────────────────────────────────────────
def _login_css() -> str:
    """Write login CSS to static file, return <link> tag (Streamlit 1.36+ compatible)."""
    import hashlib
    import pathlib
    from utils.styles import _hex_to_rgb
    branding = st.session_state.get("_branding", {})
    p = (branding.get("primary_color") or "#407E3C").strip()
    r, g, b = _hex_to_rgb(p)
    rd, gd, bd = max(0, r - 45), max(0, g - 35), max(0, b - 18)
    rl, gl, bl = min(255, r + 15), min(255, g + 47), min(255, b + 24)
    css = f""".stApp {{
    background: #F4F6F4 !important;
}}
[data-testid="stForm"] {{
    background: #FFFFFF;
    border: 1px solid #DDE8DD !important;
    border-radius: 16px !important;
    padding: 2.25rem 2.25rem 1.75rem !important;
    box-shadow: 0 8px 48px rgba(0,0,0,0.12) !important;
}}
[data-testid="stForm"] label {{
    color: #2D5C29 !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
}}
[data-testid="stForm"] input {{
    background: #F4F6F4 !important;
    border: 1.5px solid #DDE8DD !important;
    color: #1A1A1A !important;
    border-radius: 8px !important;
}}
[data-testid="stForm"] input:focus {{
    border-color: {p} !important;
    box-shadow: 0 0 0 3px rgba({r},{g},{b},0.18) !important;
}}
[data-testid="stForm"] input::placeholder {{ color: #9BA89B !important; }}
[data-testid="stFormSubmitButton"] > button {{
    background: linear-gradient(135deg, rgb({rd},{gd},{bd}), {p}) !important;
    color: #FFFFFF !important;
    font-size: 0.95rem !important;
    font-weight: 600 !important;
    padding: 0.6rem 1rem !important;
    border-radius: 8px !important;
    box-shadow: 0 4px 14px rgba({r},{g},{b},0.4) !important;
    border: none !important;
    margin-top: 0.25rem;
    width: 100% !important;
}}
[data-testid="stFormSubmitButton"] > button:hover {{
    background: linear-gradient(135deg, {p}, rgb({rl},{gl},{bl})) !important;
    color: #FFFFFF !important;
    box-shadow: 0 6px 24px rgba({r},{g},{b},0.65) !important;
    transform: translateY(-1px);
}}
.brand-title {{
    color: #1A2B1A !important;
    font-size: 1.95rem !important;
    font-weight: 800 !important;
    margin: 0 !important;
    letter-spacing: -0.02em !important;
}}
@media (max-width: 768px) {{
    .main .block-container {{
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
        padding-top: 0 !important;
    }}
    [data-testid="stForm"] {{
        padding: 1.5rem 1.1rem 1.25rem !important;
        border-radius: 10px !important;
    }}
    .brand-title {{
        font-size: 1.5rem !important;
    }}
    [data-testid="stFormSubmitButton"] > button {{
        min-height: 48px !important;
        font-size: 1rem !important;
    }}
    [data-testid="stForm"] input {{
        min-height: 44px !important;
        font-size: 1rem !important;
    }}
    [data-testid="stHorizontalBlock"] {{
        flex-wrap: wrap !important;
    }}
    [data-testid="column"] {{
        width: 100% !important;
        min-width: 100% !important;
        flex: 1 1 100% !important;
    }}
}}
/* Narrow windows (and the demo guide's split view): the sign-in card is one of three equal columns, which left it about 140px wide
   next to the open sidebar. Hide the sidebar, drop the two empty side columns and let the card be up to 440px, centred. Only the
   outer row is touched (not the logo's own columns). */
@media (max-width: 1500px) {{
    [data-testid="stSidebar"],
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="collapsedControl"] {{ display: none !important; }}
    [data-testid="stHorizontalBlock"]:not([data-testid="stColumn"] [data-testid="stHorizontalBlock"]) {{
        justify-content: center !important;
    }}
    [data-testid="stHorizontalBlock"]:not([data-testid="stColumn"] [data-testid="stHorizontalBlock"]) > [data-testid="stColumn"]:nth-child(odd) {{
        display: none !important;
    }}
    [data-testid="stHorizontalBlock"]:not([data-testid="stColumn"] [data-testid="stHorizontalBlock"]) > [data-testid="stColumn"]:nth-child(2) {{
        flex: 0 1 440px !important; width: auto !important; min-width: 0 !important; max-width: 100% !important;
    }}
}}
"""
    static_dir = pathlib.Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)
    (static_dir / "login.css").write_text(css, encoding="utf-8")
    v = hashlib.md5(css.encode()).hexdigest()[:8]
    return f'<link rel="stylesheet" href="/app/static/login.css?v={v}">'


def show_login():
    st.markdown(_login_css(), unsafe_allow_html=True)

    _, col, _ = st.columns([1, 1, 1])
    with col:
        st.markdown("<div style='height:10vh'></div>", unsafe_allow_html=True)

        # Logo + brand
        _b = st.session_state.get("_branding", {})
        _app_name  = _b.get("app_name", "RMM System")
        _tagline   = _b.get("tagline", "Remote Monitoring &amp; Management")
        _logo_data = _b.get("logo_data")

        if _logo_data:
            import base64 as _b64_mod
            try:
                _, _b64p = _logo_data.split(",", 1)
                _img_bytes = _b64_mod.b64decode(_b64p)
                _, _lc, _ = st.columns([1, 1, 1])
                with _lc:
                    st.image(_img_bytes, width=120)
                st.markdown(
                    f'<div style="text-align:center;margin-bottom:2rem">'
                    f'<h1 class="brand-title">{_app_name}</h1>'
                    f'<p style="color:#8EC88E;font-size:0.88rem;margin:6px 0 0;font-weight:500">{_tagline}</p>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            except Exception:
                _logo_data = None

        if not _logo_data:
            st.markdown(f"""
            <div style="text-align:center;margin-bottom:2rem">
                <div style="display:inline-flex;align-items:center;justify-content:center;
                            width:68px;height:68px;margin-bottom:1rem;
                            background:linear-gradient(135deg,#1A3C18,#2D5C29);
                            border-radius:18px;font-size:2rem;
                            box-shadow:0 8px 24px rgba(64,126,60,0.4)">
                    <i class="fa-solid fa-desktop" style="color:#5DB85A;font-size:2rem"></i>
                </div>
                <h1 class="brand-title">{_app_name}</h1>
                <p style="color:#8EC88E;font-size:0.88rem;margin:6px 0 0;font-weight:500">
                    {_tagline}
                </p>
            </div>
            """, unsafe_allow_html=True)

        with st.form("login_form"):
            email    = st.text_input("Email address", placeholder="admin@company.com")
            password = st.text_input("Password", type="password", placeholder="••••••••")
            st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
            submitted = st.form_submit_button("Sign In →", width='stretch')

        # Forgot password link
        st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)
        if st.button("Forgot your password?", width='stretch', key="forgot_pw_btn"):
            st.session_state["show_forgot_pw"] = not st.session_state.get("show_forgot_pw", False)
            st.rerun()

        # Forgot password form
        if st.session_state.get("show_forgot_pw"):
            st.markdown("<p style='color:#6B7B6B;font-size:0.85rem;margin:0.75rem 0 0.5rem'>Enter your email and we'll send a reset link (valid 1 hour).</p>", unsafe_allow_html=True)
            with st.form("forgot_pw_form"):
                reset_email = st.text_input("Email address", placeholder="your@email.com", key="reset_email_input")
                sent = st.form_submit_button("Send Reset Link →", width='stretch')

            if sent:
                if not reset_email:
                    st.error("Enter your email address.")
                else:
                    from utils.api_client import RMMClient
                    RMMClient.request_password_reset(reset_email)
                    st.success("If that email is registered, a reset link has been sent.")
                    st.session_state["show_forgot_pw"] = False

        _footer_name = st.session_state.get("_branding", {}).get("app_name", "RMM System")
        st.markdown(
            f'<div style="text-align:center;margin-top:1.25rem;color:#1E3A1E;font-size:0.75rem">'
            f'{_footer_name} · Authorized access only</div>',
            unsafe_allow_html=True,
        )

    if submitted:
        if not email or not password:
            st.error("Enter email and password.")
        else:
            from utils.auth import login
            with st.spinner("Authenticating…"):
                result = login(email, password)
            if result == "locked":
                locked_until = st.session_state.get("login_locked_until", "")
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(locked_until)
                    time_str = dt.strftime("%H:%M:%S")
                    st.error(f"Account locked after too many failed attempts. Auto-unlocks at {time_str}. Contact your admin to unlock early.")
                except Exception:
                    st.error("Account locked after too many failed attempts. Contact your admin or wait 5 minutes.")
            elif result == "error":
                st.error("Invalid credentials.")
            else:
                st.rerun()


# ── Home (post-login) ─────────────────────────────────────────────────────────
def show_dashboard_home():
    from utils.auth import current_user, logout, require_auth

    client = require_auth()
    user   = current_user()

    with st.sidebar:
        _role_pill = {
            "superadmin": ("#7C3AED", "#7C3AED15"),
            "admin":      ("#EF4444", "#EF444415"),
            "technician": ("#F59E0B", "#F59E0B15"),
            "viewer":     ("#22C55E", "#22C55E15"),
        }
        rc, rb = _role_pill.get(user.get("role", "viewer"), ("#8492A6", "#8492A615"))
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
                        {name}</div>
                    <span style="background:{rb};color:{rc};padding:2px 8px;border-radius:20px;
                                 font-size:0.65rem;font-weight:700;display:inline-block;margin-top:2px">
                        {user.get('role','').upper()}</span>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

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

        role = user.get("role", "")

        if role in ("admin", "superadmin"):
            if st.button("Admin Panel", width='stretch', key="nav_admin", icon=":material/admin_panel_settings:"):
                st.switch_page("pages/10_Admin.py")
            st.markdown("<div style='height:0.25rem'></div>", unsafe_allow_html=True)

        nav_section("MONITORING", first=True)
        st.page_link("pages/01_Dashboard.py",         label="Overview",          icon=":material/bar_chart:")
        st.page_link("pages/04_Devices.py",           label="Devices",           icon=":material/computer:")
        st.page_link("pages/05_Alerts.py",            label="Alerts",            icon=":material/notifications:")

        nav_section("MANAGEMENT")
        st.page_link("pages/02_Tickets.py",           label="Tickets",           icon=":material/confirmation_number:")
        st.page_link("pages/03_Customers.py",         label="Customers",         icon=":material/groups:")
        st.page_link("pages/11_Automation.py",        label="Automation",        icon=":material/smart_toy:")

        nav_section("PATCHING")
        st.page_link("pages/12_OS_Patches.py",        label="OS Patches",        icon=":material/system_update:")
        st.page_link("pages/13_Software_Patches.py",  label="Software Patches",  icon=":material/inventory_2:")

        nav_section("TOOLS")
        st.page_link("pages/16_Scripts.py",           label="Scripts",           icon=":material/code:")
        st.page_link("pages/14_Disk_Management.py",   label="Disk Management",   icon=":material/storage:")
        st.page_link("pages/15_Maintenance.py",       label="Maintenance",       icon=":material/build:")
        st.page_link("pages/07_Network_Discovery.py", label="Network Discovery", icon=":material/wifi_find:")

        if role in ("admin", "superadmin", "technician"):
            nav_section("BUSINESS")
            st.page_link("pages/08_Reports.py",       label="Reports",           icon=":material/bar_chart:")
            st.page_link("pages/09_Billing.py",       label="Billing",           icon=":material/payments:")

        st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)
        if st.button("Sign Out", width='stretch', key="home_signout", icon=":material/logout:"):
            logout()

    # Main
    st.markdown("""
    <h1 style="margin:0">RMM Dashboard</h1>
    <p style="color:#6B7B6B;margin:2px 0 0;font-size:0.88rem">System overview — live data</p>
    """, unsafe_allow_html=True)
    st.divider()

    data, err = client.get_summary()
    if err:
        st.error(f"Could not load summary: {err}")
        return

    if not data:
        st.info("No data yet. Start the agent to register devices.")
        return

    d = data["devices"]
    a = data["alerts"]
    t = data["tickets"]

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.markdown(stat_card("Total Devices", d["total"], icon="<i class='fa-solid fa-desktop'></i>"), unsafe_allow_html=True)
    with c2:
        offline = d.get("offline", 0)
        st.markdown(stat_card("Online", d["online"],
                               f"{offline} offline" if offline else "all online",
                               BRAND["success"], "<i class='fa-solid fa-circle' style='color:#22C55E'></i>"), unsafe_allow_html=True)
    with c3:
        crit = d.get("critical", 0)
        st.markdown(stat_card("Critical", crit,
                               "needs attention" if crit else "all clear",
                               BRAND["danger"] if crit else BRAND["success"],
                               "<i class='fa-solid fa-circle' style='color:#EF4444'></i>" if crit else "<i class='fa-solid fa-circle-check' style='color:#22C55E'></i>"), unsafe_allow_html=True)
    with c4:
        open_a = a["open"]
        st.markdown(stat_card("Open Alerts", open_a,
                               f"{a.get('critical',0)} critical" if open_a else "none active",
                               BRAND["warning"] if open_a else BRAND["success"],
                               "<i class='fa-solid fa-bell'></i>"), unsafe_allow_html=True)
    with c5:
        st.markdown(stat_card("Open Tickets", t["open"], icon="<i class='fa-solid fa-clipboard-list'></i>"), unsafe_allow_html=True)

    st.markdown("""
    <div style="margin-top:1.5rem;padding:0.9rem 1.1rem;background:#F0F7F0;
                border-radius:10px;border:1px solid #DDE8DD;color:#2D5C29;font-size:0.87rem">
        <i class="fa-solid fa-thumbtack"></i>&nbsp;Use the sidebar to navigate. Go to <b>Overview</b> for live charts and device health.
    </div>
    """, unsafe_allow_html=True)


def show_mfa_step():
    """Full-screen TOTP entry form shown after password login when MFA is enabled."""
    st.markdown(_login_css(), unsafe_allow_html=True)

    _, col, _ = st.columns([1, 1, 1])
    with col:
        st.markdown("<div style='height:10vh'></div>", unsafe_allow_html=True)
        st.markdown("""
        <div style="text-align:center;margin-bottom:2rem">
            <div style="display:inline-flex;align-items:center;justify-content:center;
                        width:68px;height:68px;margin-bottom:1rem;
                        background:linear-gradient(135deg,#1A3C18,#2D5C29);
                        border-radius:18px;font-size:2rem;
                        box-shadow:0 8px 24px rgba(64,126,60,0.4)">
                <i class="fa-solid fa-shield-halved" style="color:#5DB85A;font-size:2rem"></i>
            </div>
            <h1 class="brand-title">Two-Factor Auth</h1>
            <p style="color:#8EC88E;font-size:0.88rem;margin:6px 0 0;font-weight:500">
                Enter the 6-digit code from your authenticator app.
            </p>
        </div>
        """, unsafe_allow_html=True)

        with st.form("mfa_login_form"):
            code = st.text_input("Authenticator Code", placeholder="123456", max_chars=6)
            st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
            submitted = st.form_submit_button("Verify →", width='stretch')

        if st.button("← Back to login", key="mfa_back"):
            st.session_state.pop("mfa_pending_token", None)
            st.rerun()

    if submitted:
        if not code or len(code) != 6 or not code.isdigit():
            st.error("Enter a valid 6-digit code.")
        else:
            from utils.api_client import RMMClient
            mfa_token = st.session_state.get("mfa_pending_token", "")
            with st.spinner("Verifying…"):
                data, err = RMMClient.mfa_login(mfa_token, code)
            if err:
                st.error("Invalid code or session expired. Try again.")
            else:
                st.session_state.pop("mfa_pending_token", None)
                from utils.auth import establish_session
                establish_session(data["access_token"], data.get("refresh_token", ""))
                st.session_state["user"] = data["user"]
                st.rerun()


def show_force_change_password():
    """Full-screen form shown when must_change_password is True."""
    st.markdown(_login_css(), unsafe_allow_html=True)

    _, col, _ = st.columns([1, 1, 1])
    with col:
        st.markdown("<div style='height:10vh'></div>", unsafe_allow_html=True)
        st.markdown("""
        <div style="text-align:center;margin-bottom:2rem">
            <div style="display:inline-flex;align-items:center;justify-content:center;
                        width:68px;height:68px;margin-bottom:1rem;
                        background:linear-gradient(135deg,#1A3C18,#2D5C29);
                        border-radius:18px;font-size:2rem;
                        box-shadow:0 8px 24px rgba(64,126,60,0.4)">
                <i class="fa-solid fa-key" style="color:#5DB85A;font-size:2rem"></i>
            </div>
            <h1 class="brand-title">Set New Password</h1>
            <p style="color:#8EC88E;font-size:0.88rem;margin:6px 0 0;font-weight:500">
                You must change your password before continuing.
            </p>
        </div>
        """, unsafe_allow_html=True)

        with st.form("force_pw_form"):
            new_pw  = st.text_input("New Password", type="password", placeholder="Min 8 characters")
            conf_pw = st.text_input("Confirm Password", type="password", placeholder="Repeat password")
            st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
            submitted = st.form_submit_button("Set Password →", width='stretch')

    if submitted:
        import re as _re
        _pw_re = _re.compile(r'^(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()\-_=+\[\]{};:\'",.<>?/\\|`~]).{8,}$')
        if len(new_pw) < 8:
            st.error("Password must be at least 8 characters.")
        elif not _pw_re.match(new_pw):
            st.error("Password must include at least 1 uppercase letter, 1 number, and 1 special character.")
        elif new_pw != conf_pw:
            st.error("Passwords do not match.")
        else:
            from utils.api_client import RMMClient
            client = RMMClient(
                access_token=st.session_state.get("access_token", ""),
                refresh_token=st.session_state.get("refresh_token", ""),
            )
            _, err = client.force_change_password(new_pw)
            if err:
                st.error(f"Failed: {err}")
            else:
                st.session_state.pop("force_pw_change", None)
                # Refresh user object so must_change_password is cleared
                user_data, _ = client.get_me()
                if user_data:
                    st.session_state["user"] = user_data
                st.rerun()


def show_reset_password_form(reset_token: str):
    """Full-screen password reset form shown when ?reset_token= is in URL."""
    st.markdown(_login_css(), unsafe_allow_html=True)

    _, col, _ = st.columns([1, 1, 1])
    with col:
        st.markdown("<div style='height:10vh'></div>", unsafe_allow_html=True)
        st.markdown("""
        <div style="text-align:center;margin-bottom:2rem">
            <div style="display:inline-flex;align-items:center;justify-content:center;
                        width:68px;height:68px;margin-bottom:1rem;
                        background:linear-gradient(135deg,#1A3C18,#2D5C29);
                        border-radius:18px;font-size:2rem;
                        box-shadow:0 8px 24px rgba(64,126,60,0.4)">
                <i class="fa-solid fa-key" style="color:#5DB85A;font-size:2rem"></i>
            </div>
            <h1 class="brand-title">Reset Password</h1>
            <p style="color:#8EC88E;font-size:0.88rem;margin:6px 0 0;font-weight:500">
                Enter a new password for your account.
            </p>
        </div>
        """, unsafe_allow_html=True)

        with st.form("reset_pw_form"):
            new_pw  = st.text_input("New Password", type="password", placeholder="Min 8 characters")
            conf_pw = st.text_input("Confirm Password", type="password", placeholder="Repeat password")
            st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
            submitted = st.form_submit_button("Set New Password →", width='stretch')

    if submitted:
        import re as _re
        _pw_re = _re.compile(r'^(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()\-_=+\[\]{};:\'",.<>?/\\|`~]).{8,}$')
        if len(new_pw) < 8:
            st.error("Password must be at least 8 characters.")
        elif not _pw_re.match(new_pw):
            st.error("Password must include at least 1 uppercase letter, 1 number, and 1 special character.")
        elif new_pw != conf_pw:
            st.error("Passwords do not match.")
        else:
            from utils.api_client import RMMClient
            _, err = RMMClient.confirm_password_reset(reset_token, new_pw)
            if err:
                st.error(f"Reset failed: {err}. The link may have expired — request a new one.")
            else:
                st.query_params.pop("reset_token", None)
                st.session_state["reset_pw_success"] = True
                st.rerun()


# ── Route ─────────────────────────────────────────────────────────────────────
# Restore session before checking session state — without this, browser
# reload always wipes st.session_state and shows the login page. Prefers
# the opaque ?sid= session-store lookup; falls back to legacy raw
# ?tok=/&rtok= params (pre-session-store tabs, or Redis was unavailable
# when the session was created).
if "access_token" not in st.session_state:
    _sid = st.query_params.get("sid", "")
    if _sid:
        from utils.session_store import get_session as _get_session
        _at, _rt = _get_session(_sid)
        if _at:
            st.session_state["access_token"] = _at
            st.session_state["refresh_token"] = _rt
            st.session_state["_dash_session_id"] = _sid
    if "access_token" not in st.session_state:
        tok = st.query_params.get("tok", "")
        if tok:
            st.session_state["access_token"] = tok
        rtok = st.query_params.get("rtok", "")
        if rtok:
            st.session_state["refresh_token"] = rtok

reset_token_param = st.query_params.get("reset_token", "")

if reset_token_param and "access_token" not in st.session_state:
    show_reset_password_form(reset_token_param)
elif "mfa_pending_token" in st.session_state:
    show_mfa_step()
elif "access_token" not in st.session_state:
    if st.session_state.pop("reset_pw_success", False):
        st.success("Password reset successful. You can now sign in.")
    show_login()
elif st.session_state.get("user", {}).get("must_change_password"):
    show_force_change_password()
else:
    show_dashboard_home()
