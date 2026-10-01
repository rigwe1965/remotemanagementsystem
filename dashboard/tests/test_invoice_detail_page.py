"""AppTest coverage for pages/10_Invoice_Detail.py (audits/testing_audit.md Finding C5)."""
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
_ORG_RESPONSE = ({"currency": "USD"}, None)


class TestInvoiceDetailPage:
    def test_warns_when_no_invoice_selected(self):
        at = _authenticated_app_test("../pages/10_Invoice_Detail.py")
        with patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert any("No invoice selected" in w.value for w in at.warning)

    def test_renders_invoice_when_selected(self):
        # The invoice body (including the invoice number) renders entirely via
        # st.components.v1.html(invoice_html, ...) (pages/10_Invoice_Detail.py:336)
        # — an iframe, not a Streamlit element AppTest can introspect (confirmed:
        # AppTest has no .html/.components accessor at all in this Streamlit
        # version). So this test verifies the fetch was wired correctly — the
        # right invoice_id was requested — rather than the (untestable) rendered
        # HTML content.
        at = _authenticated_app_test("../pages/10_Invoice_Detail.py")
        at.session_state["_view_invoice_id"] = "i1"
        invoice = {
            "id": "i1", "invoice_number": "INV-001", "status": "paid", "total": 100.0,
            "customer_id": "c1", "period_start": "2026-01-01", "period_end": "2026-01-31",
            "device_count": 5, "per_device_rate": 20.0, "tax_rate": 0.0,
        }
        with patch("utils.api_client.RMMClient.get_invoice", return_value=(invoice, None)) as mock_get_invoice, \
             patch("utils.api_client.RMMClient.get_org_settings", return_value=_ORG_RESPONSE), \
             patch("utils.cached_calls.cached_list_customers", return_value=_CUST_RESPONSE), \
             patch("utils.api_client.RMMClient.assistant_get_conversation", return_value=(None, "skip")), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        mock_get_invoice.assert_called_once_with("i1")
        assert not at.error

    def test_shows_error_when_invoice_fails_to_load(self):
        at = _authenticated_app_test("../pages/10_Invoice_Detail.py")
        at.session_state["_view_invoice_id"] = "i1"
        with patch("utils.api_client.RMMClient.get_invoice", return_value=(None, "Not found")), \
             patch("utils.api_client.RMMClient.get_org_settings", return_value=_ORG_RESPONSE), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert any("Could not load invoice" in e.value for e in at.error)
