"""AppTest coverage for pages/05_Alerts.py (audits/testing_audit.md Finding C5)."""
import uuid
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


def _authenticated_app_test(path: str) -> AppTest:
    at = AppTest.from_file(path)
    at.session_state["access_token"] = f"fake-token-{uuid.uuid4().hex[:8]}"
    at.session_state["refresh_token"] = "fake-refresh-token"
    at.session_state["user"] = {"id": "u1", "email": "admin@test.local", "role": "admin", "full_name": "Test Admin"}
    at.session_state["_org_settings"] = {"currency": "USD", "timezone": "UTC"}
    return at


_ALERTS = ({"items": [{"id": "a1", "severity": "critical", "status": "open",
                       "device_hostname": "HOST-A", "message": "CPU high", "triggered_at": "2026-01-01T00:00:00Z"}],
            "total": 1}, None)


class TestAlertsPage:
    def test_renders_alert_summary_and_expander(self):
        at = _authenticated_app_test("../pages/05_Alerts.py")
        with patch("utils.cached_calls.cached_list_alerts", return_value=_ALERTS), \
             patch("utils.api_client.RMMClient.list_alert_rules", return_value=([], None)), \
             patch("utils.api_client.RMMClient.assistant_get_conversation", return_value=(None, "skip")), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert at.metric[0].value == "1"  # Open Alerts
        expander_labels = " ".join(e.label for e in at.expander)
        assert "CPU high" in expander_labels

    def test_shows_empty_state_when_no_alerts(self):
        at = _authenticated_app_test("../pages/05_Alerts.py")
        with patch("utils.cached_calls.cached_list_alerts", return_value=({"items": [], "total": 0}, None)), \
             patch("utils.api_client.RMMClient.list_alert_rules", return_value=([], None)), \
             patch("utils.api_client.RMMClient.assistant_get_conversation", return_value=(None, "skip")), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        assert "No alerts" in markdown_text

    def test_shows_warning_when_alerts_fail_to_load(self):
        at = _authenticated_app_test("../pages/05_Alerts.py")
        with patch("utils.cached_calls.cached_list_alerts", return_value=(None, "Connection refused")), \
             patch("utils.api_client.RMMClient.list_alert_rules", return_value=([], None)), \
             patch("utils.api_client.RMMClient.assistant_get_conversation", return_value=(None, "skip")), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert any("Could not load alerts" in w.value for w in at.warning)
