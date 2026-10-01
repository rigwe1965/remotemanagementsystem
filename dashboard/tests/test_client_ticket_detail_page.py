"""AppTest coverage for pages/_client_ticket_detail.py (audits/testing_audit.md
Finding C5). Reads the target ticket id from st.session_state["_nav_ticket_id"]."""
import uuid
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


def _authenticated_app_test(role: str = "client", ticket_id: str | None = "t1") -> AppTest:
    at = AppTest.from_file("../pages/_client_ticket_detail.py")
    at.session_state["access_token"] = f"fake-token-{uuid.uuid4().hex[:8]}"
    at.session_state["refresh_token"] = "fake-refresh-token"
    at.session_state["user"] = {"id": "u1", "email": "client@test.local", "role": role,
                                 "full_name": "Test Client", "customer_id": "c1"}
    at.session_state["_org_settings"] = {"currency": "USD", "timezone": "UTC"}
    if ticket_id is not None:
        at.session_state["_nav_ticket_id"] = ticket_id
    return at


class TestClientTicketDetailPage:
    def test_staff_role_is_redirected(self):
        at = _authenticated_app_test(role="admin")
        with patch("utils.api_client.RMMClient.get_ticket", return_value=(None, "n/a")), \
             patch("streamlit.page_link"), patch("streamlit.switch_page") as mock_switch:
            at.run()

        assert not at.exception
        mock_switch.assert_called_once_with("pages/02_Tickets.py")

    def test_no_ticket_selected_shows_error(self):
        at = _authenticated_app_test(role="client", ticket_id=None)
        with patch("streamlit.page_link"), patch("streamlit.switch_page"):
            at.run()

        assert not at.exception
        assert any("No ticket selected" in e.value for e in at.error)

    def test_renders_ticket_detail(self):
        at = _authenticated_app_test(role="client", ticket_id="t1")
        ticket = {"id": "t1", "title": "Printer jam", "priority": "low", "status": "open",
                  "created_at": "2026-01-01T00:00:00Z", "description": "Paper stuck", "comments": []}
        with patch("utils.api_client.RMMClient.get_ticket", return_value=(ticket, None)), \
             patch("streamlit.page_link"), patch("streamlit.switch_page"):
            at.run()

        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        assert "Printer jam" in markdown_text
