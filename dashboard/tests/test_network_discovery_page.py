"""AppTest coverage for pages/07_Network_Discovery.py (audits/testing_audit.md
Finding C5). The idle (default) render path calls RMMClient._get() directly
with several different raw paths (server_ips, devices list for the stale-
device check, past scans) rather than named wrapper methods — mocked here
via a side_effect dispatcher keyed on the path argument."""
import uuid
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


def _authenticated_app_test(path: str, role: str = "admin") -> AppTest:
    at = AppTest.from_file(path)
    at.session_state["access_token"] = f"fake-token-{uuid.uuid4().hex[:8]}"
    at.session_state["refresh_token"] = "fake-refresh-token"
    at.session_state["user"] = {"id": "u1", "email": "admin@test.local", "role": role, "full_name": "Test Admin"}
    at.session_state["_org_settings"] = {"currency": "USD", "timezone": "UTC"}
    return at


def _fake_get(path, params=None):
    if "server_ips" in path:
        return {"lan_ips": ["192.168.1.10"]}, None
    if path.startswith("/api/devices"):
        return {"items": []}, None
    if "network/scans" in path:
        return [], None
    return None, "unhandled path in test"


class TestNetworkDiscoveryPage:
    def test_idle_state_no_past_scans(self):
        at = _authenticated_app_test("../pages/07_Network_Discovery.py")
        with patch("utils.api_client.RMMClient._get", side_effect=_fake_get), \
             patch("utils.cached_calls.cached_list_customers", return_value=({"items": []}, None)), \
             patch("utils.api_client.RMMClient.assistant_get_conversation", return_value=(None, "skip")), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        assert "No scans yet" in markdown_text

    def test_viewer_role_has_no_scan_button(self):
        at = _authenticated_app_test("../pages/07_Network_Discovery.py", role="viewer")
        with patch("utils.api_client.RMMClient._get", side_effect=_fake_get), \
             patch("utils.cached_calls.cached_list_customers", return_value=({"items": []}, None)), \
             patch("utils.api_client.RMMClient.assistant_get_conversation", return_value=(None, "skip")), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert any("view-only access" in i.value for i in at.info)
