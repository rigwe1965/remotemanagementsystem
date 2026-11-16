"""The real address of the person making a request, when the API sits behind a proxy.

Without this, every request that arrives through a reverse proxy (nginx for the React app, the Streamlit dashboard) shows the
proxy's own address as ``request.remote_addr``. Everything keyed on that address (the login and default rate limits, the
audit log, the known-IP list and the sign-in lockout) then treats all users as ONE client: five wrong logins from anywhere
use up the login limit for everybody.

Set ``TRUSTED_PROXY_COUNT`` to the number of proxies in front of the API that APPEND to ``X-Forwarded-For``
(nginx: 1; the Streamlit dashboard, which sends the visitor's address as a single value: 1). The default, 0, changes
nothing. Never set it higher than the real count: with a larger number a client could choose its own address.
The API must not be reachable except through those proxies.
"""
import os

from werkzeug.middleware.proxy_fix import ProxyFix

MAX_PROXIES = 5


def trusted_proxy_count(environ=None) -> int:
    """TRUSTED_PROXY_COUNT as a small non-negative integer (anything unreadable counts as 0)."""
    raw = (environ if environ is not None else os.environ).get("TRUSTED_PROXY_COUNT", "0")
    try:
        n = int(str(raw).strip() or "0")
    except ValueError:
        return 0
    return max(0, min(n, MAX_PROXIES))


def apply_proxy_fix(app, count=None):
    """Make ``request.remote_addr`` the visitor's address (the Nth entry from the right of X-Forwarded-For).

    With fewer entries than ``count`` the header is ignored, so a request that skipped the proxy keeps its own address."""
    n = trusted_proxy_count() if count is None else count
    if n > 0:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=n, x_proto=0, x_host=0, x_port=0, x_prefix=0)
    return app


def waitress_options(count=None) -> dict:
    """Extra ``waitress.serve`` options so the visitor address reaches ``apply_proxy_fix``.

    Waitress deletes every ``X-Forwarded-*`` header it was not told to trust, so with the default settings ProxyFix never sees
    the visitor and ``request.remote_addr`` stays the proxy's address even when ``TRUSTED_PROXY_COUNT`` is set. When a proxy count
    is configured we keep the headers and let ProxyFix take exactly that many entries from the right (a client cannot add more).
    With the default count of 0 nothing changes and Waitress keeps discarding them."""
    n = trusted_proxy_count() if count is None else count
    return {"clear_untrusted_proxy_headers": False} if n > 0 else {}
