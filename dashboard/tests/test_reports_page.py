"""AppTest coverage for pages/08_Reports.py (audits/testing_audit.md Finding C5)."""
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


def _authenticated_app_test(path: str) -> AppTest:
    at = AppTest.from_file(path)
    at.session_state["access_token"] = "fake-token-for-apptest"
    at.session_state["refresh_token"] = "fake-refresh-token"
    at.session_state["user"] = {"id": "u1", "email": "admin@test.local", "role": "admin", "full_name": "Test Admin"}
    at.session_state["_org_settings"] = {"currency": "USD", "timezone": "UTC"}
    return at


_CUST_RESPONSE = ({"items": [{"id": "c1", "name": "Acme Corp"}], "total": 1}, None)


class TestReportsPage:
    def test_renders_report_history(self):
        at = _authenticated_app_test("../pages/08_Reports.py")
        reports = [{"id": "r1", "name": "Q1 Device Health", "template_type": "device_health",
                    "customer_id": "c1", "generated_at": "2026-01-01T00:00:00Z", "file_path": ""}]
        with patch("utils.cached_calls.cached_list_customers", return_value=_CUST_RESPONSE), \
             patch("utils.api_client.RMMClient.list_reports", return_value=(reports, None)), \
             patch("utils.api_client.RMMClient.assistant_get_conversation", return_value=(None, "skip")), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        assert "Q1 Device Health" in markdown_text

    def test_shows_empty_state_with_no_reports(self):
        at = _authenticated_app_test("../pages/08_Reports.py")
        with patch("utils.cached_calls.cached_list_customers", return_value=_CUST_RESPONSE), \
             patch("utils.api_client.RMMClient.list_reports", return_value=([], None)), \
             patch("utils.api_client.RMMClient.assistant_get_conversation", return_value=(None, "skip")), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        assert "No reports yet" in markdown_text

    def test_shows_error_on_history_load_failure(self):
        at = _authenticated_app_test("../pages/08_Reports.py")
        with patch("utils.cached_calls.cached_list_customers", return_value=_CUST_RESPONSE), \
             patch("utils.api_client.RMMClient.list_reports", return_value=(None, "Connection refused")), \
             patch("utils.api_client.RMMClient.assistant_get_conversation", return_value=(None, "skip")), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert any("Could not load report history" in e.value for e in at.error)
