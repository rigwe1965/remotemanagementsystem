"""AppTest coverage for pages/04_Devices.py (audits/testing_audit.md Finding C5).
This page fires 3 API calls in parallel via ThreadPoolExecutor (list_devices,
get_platform_counts, get_agent_update_info) — all three must be mocked or the
page can hang/error. st.tabs() content (like st.expander) executes for every
tab in a single script run, not just the visually active one, so a single
device that matches multiple tabs (e.g. "All" + "Windows") triggers its
per-row renderer (_render_agent_row, which itself calls list_customers and
get_device_metrics) more than once — those must be mocked too whenever any
device is present."""
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


class TestDevicesPage:
    def test_renders_with_no_devices(self):
        at = _authenticated_app_test("../pages/04_Devices.py")
        with patch("utils.api_client.RMMClient.list_devices", return_value=({"items": []}, None)), \
             patch("utils.api_client.RMMClient.get_platform_counts", return_value=({"by_platform": {}, "agentless": 0}, None)), \
             patch("utils.api_client.RMMClient.get_agent_update_info", return_value=({}, None)), \
             patch("utils.api_client.RMMClient.assistant_get_conversation", return_value=(None, "skip")), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        assert "Devices" in markdown_text

    def test_renders_agent_device_row(self):
        at = _authenticated_app_test("../pages/04_Devices.py")
        device = {
            "id": "d1", "hostname": "DESKTOP-ABC123", "platform": "windows",
            "ip_address": "10.0.0.5", "status": "healthy", "is_online": True,
            "is_agentless": False, "customer_name": "Acme Corp",
        }
        with patch("utils.api_client.RMMClient.list_devices", return_value=({"items": [device]}, None)), \
             patch("utils.api_client.RMMClient.get_platform_counts",
                   return_value=({"by_platform": {"windows": 1}, "agentless": 0}, None)), \
             patch("utils.api_client.RMMClient.get_agent_update_info", return_value=({}, None)), \
             patch("utils.api_client.RMMClient.list_customers", return_value=({"items": [{"id": "c1", "name": "Acme Corp"}]}, None)), \
             patch("utils.api_client.RMMClient.get_device_metrics", return_value=({}, None)), \
             patch("utils.api_client.RMMClient.assistant_get_conversation", return_value=(None, "skip")), \
             patch("streamlit.page_link"):
            at.run(timeout=15)

        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        assert "DESKTOP-ABC123" in markdown_text

    def test_hostname_is_html_escaped(self):
        """Regression test for audits/security_audit.md Finding I1 — a stored
        XSS via unescaped device.hostname/os_name/os_version/platform rendered
        with unsafe_allow_html=True. A hostname containing an HTML payload
        must render as literal escaped text, never as a live element."""
        at = _authenticated_app_test("../pages/04_Devices.py")
        payload = '<img src=x onerror="alert(1)">'
        device = {
            "id": "d1", "hostname": payload, "platform": "windows",
            "ip_address": "10.0.0.5", "status": "healthy", "is_online": True,
            "is_agentless": False, "customer_name": "Acme Corp",
        }
        with patch("utils.api_client.RMMClient.list_devices", return_value=({"items": [device]}, None)), \
             patch("utils.api_client.RMMClient.get_platform_counts",
                   return_value=({"by_platform": {"windows": 1}, "agentless": 0}, None)), \
             patch("utils.api_client.RMMClient.get_agent_update_info", return_value=({}, None)), \
             patch("utils.api_client.RMMClient.list_customers", return_value=({"items": [{"id": "c1", "name": "Acme Corp"}]}, None)), \
             patch("utils.api_client.RMMClient.get_device_metrics", return_value=({}, None)), \
             patch("utils.api_client.RMMClient.assistant_get_conversation", return_value=(None, "skip")), \
             patch("streamlit.page_link"):
            at.run(timeout=15)

        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        # The raw payload must never appear verbatim in markdown passed to
        # unsafe_allow_html=True — it must be HTML-entity-escaped.
        assert payload not in markdown_text
        assert "&lt;img src=x onerror=" in markdown_text

    def test_shows_warning_when_devices_fail_to_load(self):
        at = _authenticated_app_test("../pages/04_Devices.py")
        with patch("utils.api_client.RMMClient.list_devices", return_value=(None, "Connection refused")), \
             patch("utils.api_client.RMMClient.get_platform_counts", return_value=({}, None)), \
             patch("utils.api_client.RMMClient.get_agent_update_info", return_value=({}, None)), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert any("Could not load devices" in w.value for w in at.warning)
