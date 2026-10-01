"""AppTest coverage for pages/11_Automation.py (audits/testing_audit.md Finding C5)."""
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


class TestAutomationPage:
    def test_renders_profile_card(self):
        at = _authenticated_app_test("../pages/11_Automation.py")
        profiles = ({"items": [{"id": "p1", "name": "Nightly Cleanup", "is_active": True,
                                 "schedule_type": "daily", "last_run_at": None}]}, None)
        with patch("utils.api_client.RMMClient.list_profiles", return_value=profiles), \
             patch("utils.api_client.RMMClient.list_scripts", return_value=([], None)), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        assert "Nightly Cleanup" in markdown_text

    def test_shows_info_when_no_profiles(self):
        at = _authenticated_app_test("../pages/11_Automation.py")
        with patch("utils.api_client.RMMClient.list_profiles", return_value=({"items": []}, None)), \
             patch("utils.api_client.RMMClient.list_scripts", return_value=([], None)), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert any("No automation profiles" in i.value for i in at.info)

    def test_shows_error_on_api_failure(self):
        at = _authenticated_app_test("../pages/11_Automation.py")
        with patch("utils.api_client.RMMClient.list_profiles", return_value=(None, "Connection refused")), \
             patch("utils.api_client.RMMClient.list_scripts", return_value=([], None)), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert any("API error" in e.value for e in at.error)
