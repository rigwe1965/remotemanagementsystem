"""AppTest coverage for pages/20_Client_Portal.py (audits/testing_audit.md Finding C5).
This page is a trivial redirect (st.switch_page to 21_Client_Tickets.py) for every role."""
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


def _authenticated_app_test(path: str, role: str = "client") -> AppTest:
    at = AppTest.from_file(path)
    at.session_state["access_token"] = "fake-token-for-apptest"
    at.session_state["refresh_token"] = "fake-refresh-token"
    at.session_state["user"] = {"id": "u1", "email": "client@test.local", "role": role,
                                 "full_name": "Test Client", "customer_id": "c1"}
    at.session_state["_org_settings"] = {"currency": "USD", "timezone": "UTC"}
    return at


class TestClientPortalPage:
    def test_redirects_client_role_without_exception(self):
        at = _authenticated_app_test("../pages/20_Client_Portal.py", role="client")
        # st.switch_page(), like st.page_link(), needs the multipage registry
        # that only exists when Streamlit boots from app.py — AppTest.from_file()
        # on an isolated page can't resolve it, so it's patched to a no-op here
        # too (same gotcha documented in test_customers_page.py for page_link).
        with patch("streamlit.page_link"), patch("streamlit.switch_page"):
            at.run()

        assert not at.exception

    def test_redirects_staff_role_without_exception(self):
        at = _authenticated_app_test("../pages/20_Client_Portal.py", role="admin")
        with patch("streamlit.page_link"), patch("streamlit.switch_page"):
            at.run()

        assert not at.exception
