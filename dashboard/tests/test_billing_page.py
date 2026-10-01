"""AppTest coverage for pages/09_Billing.py (audits/testing_audit.md Finding C5)."""
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


def _authenticated_app_test(path: str) -> AppTest:
    at = AppTest.from_file(path)
    at.session_state["access_token"] = "fake-token-for-apptest"
    at.session_state["refresh_token"] = "fake-refresh-token"
    at.session_state["user"] = {"id": "u1", "email": "admin@test.local", "role": "admin", "full_name": "Test Admin"}
    at.session_state["_org_settings"] = {"currency": "USD", "timezone": "UTC"}
    return at


_CUST_RESPONSE = ({"items": [{"id": "c1", "name": "Acme Corp"}], "total": 1}, None)


class TestBillingPage:
    def test_renders_invoice_summary_metrics(self):
        at = _authenticated_app_test("../pages/09_Billing.py")
        invoices = [
            {"id": "i1", "invoice_number": "INV-001", "status": "paid", "total": 100.0,
             "customer_id": "c1", "period_start": "2026-01-01", "period_end": "2026-01-31", "device_count": 5},
            {"id": "i2", "invoice_number": "INV-002", "status": "overdue", "total": 50.0,
             "customer_id": "c1", "period_start": "2026-02-01", "period_end": "2026-02-28", "device_count": 2},
        ]
        with patch("utils.cached_calls.cached_list_customers", return_value=_CUST_RESPONSE), \
             patch("utils.api_client.RMMClient.list_invoices", return_value=(invoices, None)), \
             patch("utils.api_client.RMMClient.assistant_get_conversation", return_value=(None, "skip")), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert at.metric[0].value == "2"  # Total Invoices

    def test_shows_empty_state_with_no_invoices(self):
        at = _authenticated_app_test("../pages/09_Billing.py")
        with patch("utils.cached_calls.cached_list_customers", return_value=_CUST_RESPONSE), \
             patch("utils.api_client.RMMClient.list_invoices", return_value=([], None)), \
             patch("utils.api_client.RMMClient.assistant_get_conversation", return_value=(None, "skip")), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        assert "No invoices found" in markdown_text

    def test_shows_warning_on_load_failure(self):
        at = _authenticated_app_test("../pages/09_Billing.py")
        with patch("utils.cached_calls.cached_list_customers", return_value=_CUST_RESPONSE), \
             patch("utils.api_client.RMMClient.list_invoices", return_value=(None, "Connection refused")), \
             patch("utils.api_client.RMMClient.assistant_get_conversation", return_value=(None, "skip")), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert any("Could not load invoices" in w.value for w in at.warning)
