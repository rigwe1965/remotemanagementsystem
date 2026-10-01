"""AppTest coverage for pages/01_Dashboard.py (audits/testing_audit.md Finding C5).
See test_customers_page.py for the established pattern/gotchas this follows.

Note: the page's body is wrapped in @st.fragment(run_every=60) — AppTest still
executes the fragment body once on initial run, it just doesn't auto-rerun on
the 60s timer (no real background loop in a test). Fragment execution needs
more wall-clock time than AppTest's 3s default timeout to settle — every
at.run(timeout=15) call here passes timeout=15, or it raises 'AppTest script run timed
out after 3(s)' (observed directly, not guessed)."""
import uuid
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


def _authenticated_app_test(path: str, token_suffix: str = "") -> AppTest:
    at = AppTest.from_file(path)
    # Unique token per test — utils/cached_calls.py's @st.cache_data functions
    # key their cache by this token, and st.cache_data's cache is process-global,
    # so two tests reusing the same token could see each other's cached mock
    # results. A unique token per test avoids that collision.
    at.session_state["access_token"] = f"fake-token-{token_suffix or uuid.uuid4().hex[:8]}"
    at.session_state["refresh_token"] = "fake-refresh-token"
    at.session_state["user"] = {"id": "u1", "email": "admin@test.local", "role": "admin", "full_name": "Test Admin"}
    at.session_state["_org_settings"] = {"currency": "USD", "timezone": "UTC"}
    return at


_SUMMARY = {
    "devices": {"total": 5, "online": 4, "offline": 1, "critical": 0, "warning": 1},
    "alerts": {"open": 2, "critical": 1},
    "tickets": {"open": 3, "unassigned": 1, "sla_breached": 0, "critical": 1},
}


class TestDashboardOverviewPage:
    def test_renders_stat_cards_from_summary(self):
        at = _authenticated_app_test("../pages/01_Dashboard.py", "overview-happy")
        with patch("utils.api_client.RMMClient.get_summary", return_value=(_SUMMARY, None)), \
             patch("utils.api_client.RMMClient.get_health_map", return_value=([], None)), \
             patch("utils.api_client.RMMClient.get_recent_alerts", return_value=([], None)), \
             patch("utils.api_client.RMMClient.get_activity_feed", return_value=([], None)), \
             patch("utils.api_client.RMMClient.get_recent_events", return_value=([], None)), \
             patch("streamlit.page_link"):
            at.run(timeout=15)

        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        assert "Dashboard Overview" in markdown_text

    def test_shows_warning_banner_when_summary_fails(self):
        at = _authenticated_app_test("../pages/01_Dashboard.py", "overview-error")
        with patch("utils.api_client.RMMClient.get_summary", return_value=(None, "Connection refused")), \
             patch("streamlit.page_link"):
            at.run(timeout=15)

        assert not at.exception
        assert any("Could not load dashboard summary" in w.value for w in at.warning)
