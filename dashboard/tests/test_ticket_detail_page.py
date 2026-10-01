"""AppTest coverage for pages/_ticket_detail.py (audits/testing_audit.md
Finding C5) — staff-facing ticket detail, no role gate of its own but always
loads the full user list for the assignment tab."""
import uuid
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


def _authenticated_app_test(ticket_id: str | None = "t1", role: str = "technician") -> AppTest:
    at = AppTest.from_file("../pages/_ticket_detail.py")
    at.session_state["access_token"] = f"fake-token-{uuid.uuid4().hex[:8]}"
    at.session_state["refresh_token"] = "fake-refresh-token"
    at.session_state["user"] = {"id": "u1", "email": "tech@test.local", "role": role, "full_name": "Test Tech"}
    at.session_state["_org_settings"] = {"currency": "USD", "timezone": "UTC"}
    if ticket_id is not None:
        at.session_state["_nav_ticket_id"] = ticket_id
    return at


class TestTicketDetailPage:
    def test_no_ticket_selected_shows_error(self):
        at = _authenticated_app_test(ticket_id=None)
        with patch("utils.api_client.RMMClient.list_users", return_value=({"items": []}, None)), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert any("No ticket selected" in e.value for e in at.error)

    def test_renders_ticket_detail(self):
        at = _authenticated_app_test(ticket_id="t1")
        ticket = {"id": "t1", "title": "Server down", "priority": "critical", "status": "open",
                  "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
                  "description": "Prod server unresponsive", "comments": [], "source": "manual"}
        with patch("utils.api_client.RMMClient.get_ticket", return_value=(ticket, None)), \
             patch("utils.api_client.RMMClient.list_users", return_value=({"items": []}, None)), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        assert "Server down" in markdown_text

    def test_ticket_load_failure_shows_error(self):
        at = _authenticated_app_test(ticket_id="t1")
        with patch("utils.api_client.RMMClient.get_ticket", return_value=(None, "Not found")), \
             patch("utils.api_client.RMMClient.list_users", return_value=({"items": []}, None)), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert any("Could not load ticket" in e.value for e in at.error)
