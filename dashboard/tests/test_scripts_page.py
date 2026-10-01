"""AppTest coverage for pages/16_Scripts.py (audits/testing_audit.md Finding C5)."""
import uuid
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


def _authenticated_app_test() -> AppTest:
    at = AppTest.from_file("../pages/16_Scripts.py")
    at.session_state["access_token"] = f"fake-token-{uuid.uuid4().hex[:8]}"
    at.session_state["refresh_token"] = "fake-refresh-token"
    at.session_state["user"] = {"id": "u1", "email": "admin@test.local", "role": "admin", "full_name": "Test Admin"}
    at.session_state["_org_settings"] = {"currency": "USD", "timezone": "UTC"}
    return at


class TestScriptsPage:
    def test_renders_script_library(self):
        at = _authenticated_app_test()
        scripts = [{"id": "s1", "name": "Clean Temp Files", "file_type": "ps1",
                    "is_builtin": True, "os_target": "windows", "created_at": "2026-01-01T00:00:00Z",
                    "description": "Cleans temp dirs", "content": "Remove-Item ..."}]
        with patch("utils.api_client.RMMClient.list_scripts", return_value=(scripts, None)), \
             patch("utils.api_client.RMMClient.list_devices", return_value=({"items": []}, None)), \
             patch("utils.api_client.RMMClient.list_script_runs", return_value=({"items": []}, None)), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        expander_labels = " ".join(e.label for e in at.expander)
        assert "Clean Temp Files" in expander_labels

    def test_no_scripts_shows_info(self):
        at = _authenticated_app_test()
        with patch("utils.api_client.RMMClient.list_scripts", return_value=([], None)), \
             patch("utils.api_client.RMMClient.list_devices", return_value=({"items": []}, None)), \
             patch("utils.api_client.RMMClient.list_script_runs", return_value=({"items": []}, None)), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert any("No scripts found" in i.value for i in at.info)

    def test_api_error_shows_error_message(self):
        at = _authenticated_app_test()
        with patch("utils.api_client.RMMClient.list_scripts", return_value=(None, "Connection refused")), \
             patch("utils.api_client.RMMClient.list_script_runs", return_value=({"items": []}, None)), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert any("API error" in e.value for e in at.error)
