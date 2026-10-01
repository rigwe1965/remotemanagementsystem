"""AppTest coverage for pages/21_Client_Tickets.py (audits/testing_audit.md
Finding C5). This page doesn't import render_sidebar (client-portal pages
have their own minimal header), so no st.page_link patch is needed — but it
does call st.switch_page() to bounce staff roles to the main Tickets page,
which needs the same patch for the same AppTest multipage-registry reason."""
import uuid
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


def _authenticated_app_test(role: str = "client") -> AppTest:
    at = AppTest.from_file("../pages/21_Client_Tickets.py")
    at.session_state["access_token"] = f"fake-token-{uuid.uuid4().hex[:8]}"
    at.session_state["refresh_token"] = "fake-refresh-token"
    at.session_state["user"] = {"id": "u1", "email": "client@test.local", "role": role,
                                 "full_name": "Test Client", "customer_id": "c1"}
    at.session_state["_org_settings"] = {"currency": "USD", "timezone": "UTC"}
    return at


class TestClientTicketsPage:
    def test_staff_role_is_redirected(self):
        at = _authenticated_app_test(role="admin")
        with patch("utils.api_client.RMMClient.list_available_mdm_integrations", return_value=([], None)), \
             patch("utils.api_client.RMMClient.list_tickets", return_value=({"items": []}, None)), \
             patch("streamlit.page_link"), patch("streamlit.switch_page") as mock_switch:
            at.run()

        assert not at.exception
        mock_switch.assert_called_once_with("pages/02_Tickets.py")

    def test_client_sees_own_tickets(self):
        at = _authenticated_app_test(role="client")
        tickets = {"items": [{"id": "t1", "title": "My printer is broken", "priority": "medium",
                               "status": "open", "created_at": "2026-01-01T00:00:00Z"}]}
        with patch("utils.api_client.RMMClient.list_available_mdm_integrations", return_value=([], None)), \
             patch("utils.api_client.RMMClient.list_tickets", return_value=(tickets, None)), \
             patch("streamlit.page_link"), patch("streamlit.switch_page"):
            at.run()

        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        assert "My printer is broken" in markdown_text

    def test_no_tickets_shows_empty_state(self):
        at = _authenticated_app_test(role="client")
        with patch("utils.api_client.RMMClient.list_available_mdm_integrations", return_value=([], None)), \
             patch("utils.api_client.RMMClient.list_tickets", return_value=({"items": []}, None)), \
             patch("streamlit.page_link"), patch("streamlit.switch_page"):
            at.run()

        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        assert "No tickets yet" in markdown_text
