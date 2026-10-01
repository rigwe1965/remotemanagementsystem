"""AppTest coverage for pages/22_Usage_Monitoring.py (audits/testing_audit.md
Finding C5) — admin and superadmin only (per CLAUDE.md)."""
import uuid
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


def _authenticated_app_test(role: str) -> AppTest:
    at = AppTest.from_file("../pages/22_Usage_Monitoring.py")
    at.session_state["access_token"] = f"fake-token-{uuid.uuid4().hex[:8]}"
    at.session_state["refresh_token"] = "fake-refresh-token"
    at.session_state["user"] = {"id": "u1", "email": "sa@test.local", "role": role, "full_name": "Test User"}
    at.session_state["_org_settings"] = {"currency": "USD", "timezone": "UTC"}
    return at


_SUMMARY = ({"totals": {"calls": 100, "tokens": 5000, "estimated_cost_usd": 1.5, "error_rate": 0.01, "error_count": 1},
             "services": [{"service": "ai_assistant", "calls": 100, "input_tokens": 4000, "output_tokens": 1000,
                           "estimated_cost_usd": 1.5, "error_count": 1, "error_rate": 0.01}],
             "anomalies": []}, None)


class TestUsageMonitoringPage:
    def test_technician_role_is_blocked(self):
        """Regression test: roles below admin are still blocked on this page."""
        at = _authenticated_app_test(role="technician")
        with patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert any("Administrator access required" in e.value for e in at.error)

    def test_admin_sees_usage_summary(self):
        at = _authenticated_app_test(role="admin")
        with patch("utils.cached_calls.cached_usage_summary", return_value=_SUMMARY), \
             patch("utils.cached_calls.cached_usage_timeseries", return_value=({"points": []}, None)), \
             patch("utils.cached_calls.cached_usage_by_feature", return_value=({"items": []}, None)), \
             patch("utils.api_client.RMMClient.get_usage_alert_config", return_value=({"is_enabled": False, "spike_multiplier": 3.0}, None)), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert not at.error

    def test_superadmin_sees_usage_summary(self):
        at = _authenticated_app_test(role="superadmin")
        with patch("utils.cached_calls.cached_usage_summary", return_value=_SUMMARY), \
             patch("utils.cached_calls.cached_usage_timeseries", return_value=({"points": []}, None)), \
             patch("utils.cached_calls.cached_usage_by_feature", return_value=({"items": []}, None)), \
             patch("utils.api_client.RMMClient.get_usage_alert_config", return_value=({"is_enabled": False, "spike_multiplier": 3.0}, None)), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert not at.error

    def test_summary_load_failure_shows_error(self):
        at = _authenticated_app_test(role="superadmin")
        with patch("utils.cached_calls.cached_usage_summary", return_value=(None, "Connection refused")), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert any("Could not load usage summary" in e.value for e in at.error)
