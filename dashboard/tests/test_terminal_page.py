"""AppTest coverage for pages/14_Terminal.py (audits/testing_audit.md Finding C5).
See test_customers_page.py / test_dashboard_overview_page.py for the established
pattern. The live output panel is an @st.fragment(run_every=2) that polls
get_terminal_output — not exercised here beyond initial render with no active
session (session_id is None on first load, so the fragment body returns
immediately without polling); a real polling-loop test would need a session
already "connected" in session_state, which is covered indirectly by the
device-list/role-gate tests below instead of forcing that fragile path."""
import uuid
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


def _authenticated_app_test(role: str = "admin") -> AppTest:
    at = AppTest.from_file("../pages/14_Terminal.py")
    at.session_state["access_token"] = f"fake-token-{uuid.uuid4().hex[:8]}"
    at.session_state["refresh_token"] = "fake-refresh-token"
    at.session_state["user"] = {"id": "u1", "email": "admin@test.local", "role": role, "full_name": "Test User"}
    at.session_state["_org_settings"] = {"currency": "USD", "timezone": "UTC"}
    return at


class TestTerminalPage:
    def test_viewer_role_is_blocked(self):
        at = _authenticated_app_test(role="viewer")
        with patch("utils.api_client.RMMClient.list_devices", return_value=({"items": []}, None)), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert any("restricted" in e.value for e in at.error)

    def test_no_reachable_devices_shows_info(self):
        at = _authenticated_app_test(role="admin")
        offline_only = {"items": [{"id": "d1", "hostname": "PC1", "is_online": False, "is_agentless": False}]}
        with patch("utils.api_client.RMMClient.list_devices", return_value=(offline_only, None)), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert any("No reachable agent-managed devices" in i.value for i in at.info)

    def test_renders_device_selector_when_devices_available(self):
        at = _authenticated_app_test(role="technician")
        online = {"items": [{"id": "d1", "hostname": "PC1", "platform": "windows",
                              "is_online": True, "is_agentless": False, "status": "healthy"}]}
        with patch("utils.api_client.RMMClient.list_devices", return_value=(online, None)), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert len(at.selectbox) >= 1
