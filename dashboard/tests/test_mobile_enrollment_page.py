"""AppTest coverage for pages/19_Mobile_Enrollment.py (audits/testing_audit.md Finding C5)."""
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


def _authenticated_app_test(path: str, role: str = "admin") -> AppTest:
    at = AppTest.from_file(path)
    at.session_state["access_token"] = "fake-token-for-apptest"
    at.session_state["refresh_token"] = "fake-refresh-token"
    at.session_state["user"] = {"id": "u1", "email": "admin@test.local", "role": role, "full_name": "Test Admin"}
    at.session_state["_org_settings"] = {"currency": "USD", "timezone": "UTC"}
    return at


_INTEGRATIONS = ([
    {"id": "i1", "name": "Acme Fleet", "type": "android", "bound": False, "project_id": "acme-proj",
     "enterprise_id": None, "sync_error": None},
], None)
_CUSTOMERS = ({"items": [{"id": "c1", "name": "Acme Corp"}]}, None)
_ENROLLMENTS = ([
    {"id": "e1", "status": "enrolled", "ownership_type": "corporate", "consent_given_at": "2026-01-01"},
], None)


class TestMobileEnrollmentPage:
    def test_blocks_viewer_role(self):
        at = _authenticated_app_test("../pages/19_Mobile_Enrollment.py", role="viewer")
        with patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert any("permission" in e.value for e in at.error)

    def test_renders_integration_and_enrollments_for_admin(self):
        at = _authenticated_app_test("../pages/19_Mobile_Enrollment.py", role="admin")
        with patch("utils.api_client.RMMClient.list_mdm_integrations", return_value=_INTEGRATIONS), \
             patch("utils.api_client.RMMClient.list_customers", return_value=_CUSTOMERS), \
             patch("utils.api_client.RMMClient.list_mdm_enrollments", return_value=_ENROLLMENTS), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        expander_labels = " ".join(e.label for e in at.expander)
        assert "Acme Fleet" in expander_labels

    def test_shows_info_when_no_integrations(self):
        at = _authenticated_app_test("../pages/19_Mobile_Enrollment.py", role="admin")
        with patch("utils.api_client.RMMClient.list_mdm_integrations", return_value=([], None)), \
             patch("utils.api_client.RMMClient.list_customers", return_value=_CUSTOMERS), \
             patch("utils.api_client.RMMClient.list_mdm_enrollments", return_value=([], None)), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        info_text = " ".join(i.value for i in at.info)
        assert "No Android MDM integrations" in info_text
        assert "No enrollments yet" in info_text
