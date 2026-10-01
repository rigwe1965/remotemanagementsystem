"""AppTest coverage for pages/06_App_Center.py (audits/testing_audit.md Finding C5)."""
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


_DEVICES = ({"items": [{"id": "d1", "hostname": "HOST-A"}, {"id": "d2", "hostname": "HOST-B"}]}, None)
_SOFTWARE = ([{"name": "Google Chrome", "version": "120.0", "publisher": "Google LLC",
               "source": "winget", "last_seen": "2026-01-01T00:00:00Z"}], None)


class TestAppCenterPage:
    def test_renders_software_list_for_selected_device(self):
        at = _authenticated_app_test("../pages/06_App_Center.py")
        with patch("utils.api_client.RMMClient.list_devices", return_value=_DEVICES), \
             patch("utils.api_client.RMMClient.get_device_software", return_value=_SOFTWARE), \
             patch("utils.api_client.RMMClient.assistant_get_conversation", return_value=(None, "skip")), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        assert "Google Chrome" in markdown_text

    def test_shows_empty_state_when_no_software_found(self):
        at = _authenticated_app_test("../pages/06_App_Center.py")
        with patch("utils.api_client.RMMClient.list_devices", return_value=_DEVICES), \
             patch("utils.api_client.RMMClient.get_device_software", return_value=([], None)), \
             patch("utils.api_client.RMMClient.assistant_get_conversation", return_value=(None, "skip")), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        assert "No software found" in markdown_text

    def test_stops_with_warning_when_device_list_fails(self):
        at = _authenticated_app_test("../pages/06_App_Center.py")
        with patch("utils.api_client.RMMClient.list_devices", return_value=(None, "Connection refused")), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert any("Could not load devices" in w.value for w in at.warning)
