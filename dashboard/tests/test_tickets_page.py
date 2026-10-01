"""AppTest coverage for pages/02_Tickets.py (audits/testing_audit.md Finding C5)."""
import uuid
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


def _authenticated_app_test(path: str, role: str = "admin") -> AppTest:
    at = AppTest.from_file(path)
    at.session_state["access_token"] = f"fake-token-{uuid.uuid4().hex[:8]}"
    at.session_state["refresh_token"] = "fake-refresh-token"
    at.session_state["user"] = {"id": "u1", "email": "admin@test.local", "role": role, "full_name": "Test Admin"}
    at.session_state["_org_settings"] = {"currency": "USD", "timezone": "UTC"}
    return at


_TICKETS = ({"items": [{"id": "t1abcdef", "title": "Printer jam", "status": "open",
                        "priority": "high", "customer_name": "Acme Corp", "assignee_name": None,
                        "source": "manual", "created_at": "2026-01-01T00:00:00Z"}]}, None)
_CUSTOMERS = ({"items": [{"id": "c1", "name": "Acme Corp"}]}, None)


class TestTicketsPage:
    def test_renders_ticket_row(self):
        at = _authenticated_app_test("../pages/02_Tickets.py")
        with patch("utils.api_client.RMMClient.list_tickets", return_value=_TICKETS), \
             patch("utils.api_client.RMMClient.list_customers", return_value=_CUSTOMERS), \
             patch("utils.api_client.RMMClient.assistant_get_conversation", return_value=(None, "skip")), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        assert "Printer jam" in markdown_text

    def test_shows_empty_state_when_no_tickets(self):
        at = _authenticated_app_test("../pages/02_Tickets.py")
        with patch("utils.api_client.RMMClient.list_tickets", return_value=({"items": []}, None)), \
             patch("utils.api_client.RMMClient.list_customers", return_value=_CUSTOMERS), \
             patch("utils.api_client.RMMClient.assistant_get_conversation", return_value=(None, "skip")), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        assert "No tickets found" in markdown_text

    def test_shows_warning_when_tickets_fail_to_load(self):
        at = _authenticated_app_test("../pages/02_Tickets.py")
        with patch("utils.api_client.RMMClient.list_tickets", return_value=(None, "Connection refused")), \
             patch("utils.api_client.RMMClient.list_customers", return_value=_CUSTOMERS), \
             patch("utils.api_client.RMMClient.assistant_get_conversation", return_value=(None, "skip")), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert any("Could not load tickets" in w.value for w in at.warning)
