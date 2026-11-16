"""The visitor's address, handed to the API for sign-in protection.

The dashboard calls the API from its own server, so without this the API sees every visitor as the dashboard's address and its
per-person protections (login rate limit, sign-in lockout, audit log) cannot tell people apart. Only the sign-in, two-step code and
password-reset-request calls send it (see api_client.py).

DASHBOARD_TRUSTED_PROXY_COUNT is the number of trailing ``X-Forwarded-For`` entries added by the proxies in front of Streamlit
(for example 1 behind one nginx). With 0 (default) Streamlit's own view of the connection is used; Streamlit reports none for
``localhost``, and then nothing is sent. The API only believes the value when its own TRUSTED_PROXY_COUNT is set (see the API's
utils/client_ip.py), and a value that is not a valid address is never sent.
"""
import ipaddress
import os

MAX_PROXIES = 5


def trusted_count(environ=None) -> int:
    raw = (environ if environ is not None else os.environ).get("DASHBOARD_TRUSTED_PROXY_COUNT", "0")
    try:
        n = int(str(raw).strip() or "0")
    except ValueError:
        return 0
    return max(0, min(n, MAX_PROXIES))


def _valid(value):
    try:
        return str(ipaddress.ip_address(str(value).strip()))
    except ValueError:
        return None


def visitor_ip(headers=None, count=None, direct=None):
    """The visitor's address, or None when it cannot be told. Arguments exist for tests; by default they come from Streamlit."""
    n = trusted_count() if count is None else count
    if n > 0:
        if headers is None:
            try:
                import streamlit as st
                headers = st.context.headers
            except Exception:
                return None
        raw = headers.get("X-Forwarded-For") if headers else None
        parts = [p.strip() for p in str(raw or "").split(",") if p.strip()]
        return _valid(parts[-n]) if len(parts) >= n else None
    if direct is None:
        try:
            import streamlit as st
            direct = st.context.ip_address
        except Exception:
            direct = None
    return _valid(direct) if direct else None


def forward_headers() -> dict:
    """Headers that tell the API who is signing in ({} when unknown)."""
    ip = visitor_ip()
    return {"X-Forwarded-For": ip} if ip else {}
