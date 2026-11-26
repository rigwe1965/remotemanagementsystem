"""The proxy setting must survive the real server (Waitress), not only Flask's test client.

Waitress removes X-Forwarded-* headers unless told to keep them; with the old ``serve(app, ...)`` call TRUSTED_PROXY_COUNT=1 did
nothing in the hosted demo and every visitor kept the proxy's address (found on the live demo after the first deploy of the lockout
change)."""
import threading
import time
import urllib.request

from flask import Flask, request
from waitress.server import create_server

from utils.client_ip import apply_proxy_fix, waitress_options


def _remote_addr_seen_by_flask(count, forwarded_for="203.0.113.9"):
    app = Flask(__name__)
    apply_proxy_fix(app, count=count)

    @app.route("/ip")
    def ip():
        return request.remote_addr

    server = create_server(app, host="127.0.0.1", port=0, **waitress_options(count))
    threading.Thread(target=server.run, daemon=True).start()
    try:
        time.sleep(0.2)
        req = urllib.request.Request(f"http://127.0.0.1:{server.effective_port}/ip", headers={"X-Forwarded-For": forwarded_for})
        return urllib.request.urlopen(req, timeout=5).read().decode()
    finally:
        server.close()


def test_visitor_address_reaches_flask_through_waitress():
    assert _remote_addr_seen_by_flask(1) == "203.0.113.9"


def test_only_the_trusted_entry_counts():
    # a client that prepends its own entries cannot choose its address: the entry added by the one trusted proxy wins
    assert _remote_addr_seen_by_flask(1, "198.51.100.1, 203.0.113.9") == "203.0.113.9"


def test_default_count_zero_ignores_the_header():
    assert _remote_addr_seen_by_flask(0) == "127.0.0.1"
    assert waitress_options(0) == {}
