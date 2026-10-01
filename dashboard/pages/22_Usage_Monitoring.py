"""Usage Monitoring — API & AI token usage, admin/superadmin-only."""
import streamlit as st
import pandas as pd

from utils.auth import require_auth, current_user, logout
from utils.nav import render_sidebar
from utils.ai_assistant import render_ai_assistant
from utils.styles import inject_css, BRAND, stat_card, section_header
from utils.formatters import fmt_currency
from utils.sanitize import esc
from utils.cached_calls import cached_usage_summary, cached_usage_timeseries, cached_usage_by_feature

st.set_page_config(page_title="Usage Monitoring — RMM", layout="wide")
inject_css()

client = require_auth()
render_sidebar()
user = current_user() or {}

# ── Role guard — admin and superadmin only ───────────────────────────────────────
if user.get("role") not in ("admin", "superadmin"):
    st.error("Administrator access required. This page is restricted to admin and superadmin accounts.")
    if st.button("Sign Out / Switch Account", type="primary"):
        logout()
    st.stop()

st.markdown(
    '<h1 style="margin:0">Usage Monitoring</h1>'
    '<p style="color:#6B7B6B;margin:2px 0 1rem;font-size:0.88rem">'
    'API calls, AI token consumption, and estimated cost — visible only to Administrators</p>',
    unsafe_allow_html=True,
)

token = st.session_state.get("access_token", "")

range_label = st.radio("Range", ["Today", "7 days", "30 days"], index=1, horizontal=True, label_visibility="collapsed")
range_key = {"Today": "today", "7 days": "7d", "30 days": "30d"}[range_label]

summary, err = cached_usage_summary(token, range=range_key)
if err:
    st.error(f"Could not load usage summary: {err}")
    st.stop()

totals = summary.get("totals", {})
services = summary.get("services", [])
anomalies = summary.get("anomalies", [])

# ── Anomaly banner ───────────────────────────────────────────────────────────────
if anomalies:
    lines = "<br>".join(
        f"<b>{esc(a['service'])}</b>: {a['current_hour_count']} calls in the last hour "
        f"({a['multiplier']}x the 7-day average of {a['baseline_avg']})"
        for a in anomalies
    )
    st.markdown(
        f'<div style="background:#FEF2F2;border:1px solid #FCA5A5;border-radius:10px;'
        f'padding:0.9rem 1.2rem;margin-bottom:1rem;color:#991B1B;font-size:0.85rem">'
        f'<b>Usage spike detected</b><br>{lines}</div>',
        unsafe_allow_html=True,
    )

# ── KPI tiles ─────────────────────────────────────────────────────────────────────
k1, k2, k3, k4 = st.columns(4)
with k1:
    st.markdown(stat_card("API Calls", f"{totals.get('calls', 0):,}", subtitle=range_label,
                           accent=BRAND["primary"]), unsafe_allow_html=True)
with k2:
    st.markdown(stat_card("Tokens", f"{totals.get('tokens', 0):,}", subtitle="AI Assistant",
                           accent=BRAND["info"]), unsafe_allow_html=True)
with k3:
    st.markdown(stat_card("Estimated Cost", fmt_currency(totals.get("estimated_cost_usd", 0)),
                           subtitle="AI Assistant only", accent=BRAND["warning"]), unsafe_allow_html=True)
with k4:
    err_rate = totals.get("error_rate", 0) or 0
    accent = BRAND["danger"] if err_rate > 0.05 else BRAND["success"]
    st.markdown(stat_card("Error Rate", f"{err_rate * 100:.1f}%", subtitle=f"{totals.get('error_count', 0)} errors",
                           accent=accent), unsafe_allow_html=True)

st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)

# ── Per-service breakdown ─────────────────────────────────────────────────────────
st.markdown(section_header("By Service", "Which service, integration, or process is driving usage"),
            unsafe_allow_html=True)

if not services:
    st.info("No usage recorded yet for this range.")
else:
    df = pd.DataFrame(services)
    df_display = df.rename(columns={
        "service": "Service", "calls": "Calls", "input_tokens": "Input Tokens",
        "output_tokens": "Output Tokens", "estimated_cost_usd": "Est. Cost ($)",
        "error_count": "Errors", "error_rate": "Error Rate",
    })
    df_display["Error Rate"] = (df_display["Error Rate"] * 100).round(1).astype(str) + "%"
    st.dataframe(df_display, width="stretch", hide_index=True)

    st.bar_chart(df.set_index("service")["calls"], height=240, width="stretch")

st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)

# ── Timeseries ────────────────────────────────────────────────────────────────────
st.markdown(section_header("Trend", "Calls, tokens, or estimated cost over time"), unsafe_allow_html=True)

tcol1, tcol2 = st.columns([1, 1])
with tcol1:
    service_options = ["All services"] + [s["service"] for s in services]
    ts_service_label = st.selectbox("Service", service_options, key="ts_service")
with tcol2:
    ts_metric_label = st.selectbox("Metric", ["Calls", "Tokens", "Estimated Cost"], key="ts_metric")

ts_service = None if ts_service_label == "All services" else ts_service_label
ts_metric = {"Calls": "calls", "Tokens": "tokens", "Estimated Cost": "cost"}[ts_metric_label]

ts_data, ts_err = cached_usage_timeseries(token, range=range_key, service=ts_service, metric=ts_metric)
if ts_err:
    st.warning(f"Could not load trend chart: {ts_err}")
else:
    points = ts_data.get("points", [])
    if points:
        ts_df = pd.DataFrame(points).set_index("bucket")
        st.line_chart(ts_df, height=240, width="stretch")
    else:
        st.info("No data points for this selection.")

st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)

# ── Top features / users ──────────────────────────────────────────────────────────
st.markdown(section_header("Top Features & Users", "Which page, integration action, or user is responsible"),
            unsafe_allow_html=True)

feat_data, feat_err = cached_usage_by_feature(token, range=range_key)
if feat_err:
    st.warning(f"Could not load feature breakdown: {feat_err}")
else:
    items = feat_data.get("items", [])
    if items:
        feat_df = pd.DataFrame(items)
        feat_df["responsible"] = feat_df.apply(
            lambda r: r["user_email"] or r["user_id"] or "system", axis=1
        )
        feat_display = feat_df[["service", "feature", "responsible", "calls", "input_tokens",
                                 "output_tokens", "estimated_cost_usd"]].rename(columns={
            "service": "Service", "feature": "Feature", "responsible": "User / Process",
            "calls": "Calls", "input_tokens": "Input Tokens", "output_tokens": "Output Tokens",
            "estimated_cost_usd": "Est. Cost ($)",
        })
        st.dataframe(feat_display, width="stretch", hide_index=True)
    else:
        st.info("No feature-level data yet.")

st.markdown('<div style="height:0.75rem"></div>', unsafe_allow_html=True)

# ── Alert configuration ───────────────────────────────────────────────────────────
with st.expander("Spike Alert Configuration", expanded=False):
    cfg, cfg_err = client.get_usage_alert_config()
    if cfg_err:
        st.error(f"Could not load alert config: {cfg_err}")
    else:
        with st.form("usage_alert_config_form"):
            is_enabled = st.toggle("Send real notifications on usage spikes", value=cfg.get("is_enabled", False))
            spike_multiplier = st.number_input(
                "Spike multiplier (trigger when usage exceeds N× the 7-day average)",
                min_value=1.5, max_value=20.0, value=float(cfg.get("spike_multiplier", 3.0)), step=0.5,
            )
            channels = cfg.get("notification_channels", {}) or {}
            emails = st.text_input("Notification emails (comma-separated)",
                                    value=", ".join(channels.get("email", [])))
            slack_urls = st.text_input("Slack webhook URL(s) (comma-separated)",
                                        value=", ".join(channels.get("slack", [])))
            teams_urls = st.text_input("Teams webhook URL(s) (comma-separated)",
                                        value=", ".join(channels.get("teams", [])))
            webhook_urls = st.text_input("Generic webhook URL(s) (comma-separated)",
                                          value=", ".join(channels.get("webhook", [])))

            if st.form_submit_button("Save"):
                new_channels = {
                    "email": [e.strip() for e in emails.split(",") if e.strip()],
                    "slack": [u.strip() for u in slack_urls.split(",") if u.strip()],
                    "teams": [u.strip() for u in teams_urls.split(",") if u.strip()],
                    "webhook": [u.strip() for u in webhook_urls.split(",") if u.strip()],
                }
                result, save_err = client.update_usage_alert_config({
                    "is_enabled": is_enabled,
                    "spike_multiplier": spike_multiplier,
                    "notification_channels": new_channels,
                })
                if save_err:
                    st.error(f"Could not save: {save_err}")
                else:
                    st.success("Alert configuration saved.")
                    st.cache_data.clear()

st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)

# ── Report export ──────────────────────────────────────────────────────────────────
st.markdown(section_header("Export", "Generate a downloadable API & Token Usage report"), unsafe_allow_html=True)
if st.button("Generate API & Token Usage Report", icon=":material/download:"):
    with st.spinner("Queuing report..."):
        result, gen_err = client.generate_report({"template_type": "api_usage"})
    if gen_err:
        st.error(f"Could not generate report: {gen_err}")
    else:
        st.success("Report queued — find it in Reports → Report History shortly.")

render_ai_assistant("Usage Monitoring", {"context": "navigation_only"})
