"""AppTest coverage for pages/13_Software_Patches.py (audits/testing_audit.md
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


_ONLINE_DEVICE = {"id": "d1", "hostname": "WIN-HOST-1", "is_online": True, "is_agentless": False}


class TestSoftwarePatchesPage:
    def test_shows_empty_state_when_no_online_devices(self):
        at = _authenticated_app_test("../pages/13_Software_Patches.py")
        with patch("utils.api_client.RMMClient.list_devices", return_value=({"items": []}, None)), \
             patch("streamlit.page_link"):
            at.run()
        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        assert "No online devices" in markdown_text

    def test_renders_with_one_online_device(self):
        at = _authenticated_app_test("../pages/13_Software_Patches.py")
        # st.selectbox auto-selects the first option on a fresh run, so
        # get_device_software() is called eagerly for the default device.
        with patch("utils.api_client.RMMClient.list_devices", return_value=({"items": [_ONLINE_DEVICE]}, None)), \
             patch("utils.api_client.RMMClient.get_device_software", return_value=({"items": []}, None)), \
             patch("streamlit.page_link"):
            at.run()
        assert not at.exception

    def test_shows_warning_when_device_list_fails(self):
        at = _authenticated_app_test("../pages/13_Software_Patches.py")
        with patch("utils.api_client.RMMClient.list_devices", return_value=(None, "Connection refused")), \
             patch("streamlit.page_link"):
            at.run()
        assert not at.exception
        assert any("Could not load devices" in w.value for w in at.warning)
