"""AppTest coverage for pages/10_Admin.py (audits/testing_audit.md Finding C5).
This page has 6 tabs (System Info, Audit Log, Users, Departments, Org
Settings, AI Triage); Streamlit executes every tab's body on each script run
(same as st.expander), so a baseline render needs every client call across
all 6 tabs mocked, not just the visually "active" one — hence the long mock
list below despite this being a single smoke test."""
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


class TestAdminPage:
    def test_renders_all_tabs_with_empty_data(self):
        at = _authenticated_app_test("../pages/10_Admin.py")
        with patch("utils.api_client.RMMClient._get", return_value=({"status": "ok"}, None)), \
             patch("utils.api_client.RMMClient.get_org_token", return_value=({"org_token": "tok123"}, None)), \
             patch("utils.api_client.RMMClient.get_server_ips", return_value=({"lan_ips": []}, None)), \
             patch("utils.api_client.RMMClient.get_activity_feed", return_value=([], None)), \
             patch("utils.api_client.RMMClient.list_departments", return_value=([], None)), \
             patch("utils.api_client.RMMClient.list_users", return_value=({"items": [], "total": 0, "pages": 0}, None)), \
             patch("utils.api_client.RMMClient.get_org_settings", return_value=({"currency": "USD", "timezone": "UTC"}, None)), \
             patch("utils.api_client.RMMClient.list_triage_categories", return_value=([], None)), \
             patch("utils.api_client.RMMClient.assistant_get_conversation", return_value=(None, "skip")), \
             patch("streamlit.page_link"):
            at.run(timeout=15)

        assert not at.exception

    def test_lists_active_user_in_items_key(self):
        """Regression-style check for audits/code_duplication_audit.md Finding N2
        — the admin/users response key is "items", not the old "users"."""
        at = _authenticated_app_test("../pages/10_Admin.py")
        users_resp = ({"items": [{"id": "u2", "email": "tech@test.local", "full_name": "Tech User",
                                   "role": "technician", "is_active": True}], "total": 1, "pages": 1}, None)
        with patch("utils.api_client.RMMClient._get", return_value=({"status": "ok"}, None)), \
             patch("utils.api_client.RMMClient.get_org_token", return_value=({"org_token": "tok123"}, None)), \
             patch("utils.api_client.RMMClient.get_server_ips", return_value=({"lan_ips": []}, None)), \
             patch("utils.api_client.RMMClient.get_activity_feed", return_value=([], None)), \
             patch("utils.api_client.RMMClient.list_departments", return_value=([], None)), \
             patch("utils.api_client.RMMClient.list_users", return_value=users_resp), \
             patch("utils.api_client.RMMClient.get_org_settings", return_value=({"currency": "USD", "timezone": "UTC"}, None)), \
             patch("utils.api_client.RMMClient.list_triage_categories", return_value=([], None)), \
             patch("utils.api_client.RMMClient.assistant_get_conversation", return_value=(None, "skip")), \
             patch("streamlit.page_link"):
            at.run(timeout=15)

        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        assert "tech@test.local" in markdown_text

    def test_renders_triage_category_row(self):
        at = _authenticated_app_test("pages/10_Admin.py")
        cats_resp = ([{
            "id": "cat1", "code": "account_access", "label": "Account & Access",
            "description": "Password resets and locked accounts.", "is_active": True,
            "auto_resolve_enabled": False, "shadow_mode": True, "confidence_threshold": 0.85,
            "auto_close_days": None,
        }], None)
        with patch("utils.api_client.RMMClient._get", return_value=({"status": "ok"}, None)), \
             patch("utils.api_client.RMMClient.get_org_token", return_value=({"org_token": "tok123"}, None)), \
             patch("utils.api_client.RMMClient.get_server_ips", return_value=({"lan_ips": []}, None)), \
             patch("utils.api_client.RMMClient.get_activity_feed", return_value=([], None)), \
             patch("utils.api_client.RMMClient.list_departments", return_value=([], None)), \
             patch("utils.api_client.RMMClient.list_users", return_value=({"items": [], "total": 0, "pages": 0}, None)), \
             patch("utils.api_client.RMMClient.get_org_settings", return_value=({"currency": "USD", "timezone": "UTC"}, None)), \
             patch("utils.api_client.RMMClient.list_triage_categories", return_value=cats_resp), \
             patch("utils.api_client.RMMClient.assistant_get_conversation", return_value=(None, "skip")), \
             patch("streamlit.page_link"):
            at.run(timeout=15)

        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        assert "Account &amp; Access" in markdown_text or "Account & Access" in markdown_text
