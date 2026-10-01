"""AppTest coverage for pages/15_Maintenance.py (audits/testing_audit.md Finding C5)."""
import uuid
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


def _authenticated_app_test() -> AppTest:
    at = AppTest.from_file("../pages/15_Maintenance.py")
    at.session_state["access_token"] = f"fake-token-{uuid.uuid4().hex[:8]}"
    at.session_state["refresh_token"] = "fake-refresh-token"
    at.session_state["user"] = {"id": "u1", "email": "admin@test.local", "role": "admin", "full_name": "Test Admin"}
    at.session_state["_org_settings"] = {"currency": "USD", "timezone": "UTC"}
    return at


class TestMaintenancePage:
    def test_no_online_devices_shows_message(self):
        at = _authenticated_app_test()
        offline = {"items": [{"id": "d1", "hostname": "PC1", "is_online": False}]}
        with patch("utils.api_client.RMMClient.list_devices", return_value=(offline, None)), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        assert "No online devices" in markdown_text

    def test_renders_device_info_card(self):
        at = _authenticated_app_test()
        online = {"items": [{
            "id": "d1", "hostname": "PC-MAINT-01", "is_online": True,
            "ip_address": "10.0.0.5", "os_name": "Windows", "os_version": "11",
            "platform": "windows", "last_seen": "2026-01-01T00:00:00Z",
        }]}
        with patch("utils.api_client.RMMClient.list_devices", return_value=(online, None)), \
             patch("utils.api_client.RMMClient._get", return_value=(None, "no history")), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        assert "PC-MAINT-01" in markdown_text

    def test_api_error_loading_devices_shows_warning(self):
        at = _authenticated_app_test()
        with patch("utils.api_client.RMMClient.list_devices", return_value=(None, "Connection refused")), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert any("Could not load devices" in w.value for w in at.warning)
