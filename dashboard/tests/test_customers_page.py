"""First attempt at Streamlit-native page testing (audits/testing_audit.md
Finding C5) using streamlit.testing.v1.AppTest — no browser needed. Seeds
session_state to skip require_auth()'s network calls (get_me/org_settings)
and mocks RMMClient.list_customers so the page never touches a real API."""
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


def _authenticated_app_test(path: str) -> AppTest:
    at = AppTest.from_file(path)
    at.session_state["access_token"] = "fake-token-for-apptest"
    at.session_state["refresh_token"] = "fake-refresh-token"
    at.session_state["user"] = {"id": "u1", "email": "admin@test.local", "role": "admin", "full_name": "Test Admin"}
    at.session_state["_org_settings"] = {"currency": "USD", "timezone": "UTC"}
    return at


class TestCustomersPage:
    def test_renders_customer_names(self):
        at = _authenticated_app_test("../pages/03_Customers.py")
        fake_response = (
            {"items": [{"id": "c1", "name": "Acme Corp", "email": None, "tier": "standard",
                        "device_count": 3, "online_count": 1, "created_at": "2026-01-01T00:00:00Z"}],
             "total": 1, "page": 1, "pages": 1},
            None,
        )
        # AppTest.from_file() runs pages/03_Customers.py in isolation, but
        # render_sidebar() (utils/nav.py) calls st.page_link("../pages/01_Dashboard.py", ...)
        # for every nav item — Streamlit's page_link() resolves that path against
        # the app's multipage registry, which AppTest never builds when a single
        # page file is the entry point (only populated when Streamlit boots from
        # app.py itself). No-op it here so the rest of the page can be verified;
        # see audits/testing_audit.md Finding C5 for the real fix (AppTest.from_file
        # on app.py + navigating to the target page, not yet attempted).
        with patch("utils.api_client.RMMClient.list_customers", return_value=fake_response), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        # Customer name renders as an st.expander() label (see pages/03_Customers.py's
        # expander_label = f"{name}  ·  {tier} ..."), not plain markdown text.
        expander_labels = " ".join(e.label for e in at.expander)
        assert "Acme Corp" in expander_labels

    def test_shows_error_banner_on_api_failure(self):
        at = _authenticated_app_test("../pages/03_Customers.py")
        with patch("utils.api_client.RMMClient.list_customers", return_value=(None, "Connection refused")), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
