"""AppTest coverage for pages/12_OS_Patches.py (audits/testing_audit.md Finding C5)."""
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


class TestOsPatchesPage:
    def test_renders_pending_patch(self):
        at = _authenticated_app_test("../pages/12_OS_Patches.py")
        pending = ([{"id": "p1", "patch_name": "KB123456", "patch_type": "security",
                      "status": "pending", "device_hostname": "HOST-A"}], None)
        with patch("utils.api_client.RMMClient.get_patch_summary", return_value=({}, None)), \
             patch("utils.api_client.RMMClient.get_pending_patches", return_value=pending), \
             patch("utils.api_client.RMMClient.list_patches", return_value=({"items": []}, None)), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        assert "KB123456" in markdown_text

    def test_shows_error_when_summary_fails(self):
        at = _authenticated_app_test("../pages/12_OS_Patches.py")
        with patch("utils.api_client.RMMClient.get_patch_summary", return_value=(None, "Connection refused")), \
             patch("utils.api_client.RMMClient.get_pending_patches", return_value=([], None)), \
             patch("utils.api_client.RMMClient.list_patches", return_value=({"items": []}, None)), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
