"""AppTest coverage for pages/14_Disk_Management.py (audits/testing_audit.md
Finding C5)."""
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


def _authenticated_app_test(path: str) -> AppTest:
    at = AppTest.from_file(path)
    at.session_state["access_token"] = "fake-token-for-apptest"
    at.session_state["refresh_token"] = "fake-refresh-token"
    at.session_state["user"] = {"id": "u1", "email": "admin@test.local", "role": "admin", "full_name": "Test Admin"}
    at.session_state["_org_settings"] = {"currency": "USD", "timezone": "UTC"}
    return at


class TestDiskManagementPage:
    def test_shows_no_devices_registered(self):
        at = _authenticated_app_test("../pages/14_Disk_Management.py")
        with patch("utils.api_client.RMMClient.list_devices", return_value=({"items": []}, None)), \
             patch("streamlit.page_link"):
            at.run()
        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        assert "No devices registered" in markdown_text

    def test_shows_no_disk_metrics_for_device_without_metrics(self):
        device = {"id": "d1", "hostname": "WIN-HOST-1", "latest_metrics": None}
        at = _authenticated_app_test("../pages/14_Disk_Management.py")
        with patch("utils.api_client.RMMClient.list_devices", return_value=({"items": [device]}, None)), \
             patch("streamlit.page_link"):
            at.run()
        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        assert "No disk metrics available" in markdown_text

    def test_renders_disk_gauges_when_metrics_present(self):
        device = {
            "id": "d1", "hostname": "WIN-HOST-1",
            "latest_metrics": {"disks": [{"drive": "C:", "used_pct": 45.0, "total_gb": 500, "used_gb": 225}]},
        }
        at = _authenticated_app_test("../pages/14_Disk_Management.py")
        with patch("utils.api_client.RMMClient.list_devices", return_value=({"items": [device]}, None)), \
             patch("streamlit.page_link"):
            at.run()
        assert not at.exception

    def test_shows_warning_when_device_list_fails(self):
        at = _authenticated_app_test("../pages/14_Disk_Management.py")
        with patch("utils.api_client.RMMClient.list_devices", return_value=(None, "Connection refused")), \
             patch("streamlit.page_link"):
            at.run()
        assert not at.exception
        assert any("Could not load devices" in w.value for w in at.warning)
