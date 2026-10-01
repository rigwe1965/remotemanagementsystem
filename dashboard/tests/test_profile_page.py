"""AppTest coverage for pages/17_Profile.py (audits/testing_audit.md Finding C5).
The page makes no API calls on initial render (avatar/password/MFA actions are
all button/form-submit gated), so no RMMClient mocking is needed for these
smoke tests beyond auth."""
import uuid
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


def _authenticated_app_test(mfa_enabled: bool = False) -> AppTest:
    at = AppTest.from_file("../pages/17_Profile.py")
    at.session_state["access_token"] = f"fake-token-{uuid.uuid4().hex[:8]}"
    at.session_state["refresh_token"] = "fake-refresh-token"
    at.session_state["user"] = {
        "id": "u1", "email": "admin@test.local", "role": "admin", "full_name": "Test Admin",
        "mfa_enabled": mfa_enabled, "avatar_data": None,
    }
    at.session_state["_org_settings"] = {"currency": "USD", "timezone": "UTC"}
    return at


class TestProfilePage:
    def test_renders_account_info(self):
        at = _authenticated_app_test()
        with patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        assert "admin@test.local" in markdown_text

    def test_mfa_disabled_shows_enable_button(self):
        at = _authenticated_app_test(mfa_enabled=False)
        with patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        button_labels = [b.label for b in at.button]
        assert any("Enable MFA" in lbl for lbl in button_labels)

    def test_mfa_enabled_shows_disable_form(self):
        at = _authenticated_app_test(mfa_enabled=True)
        with patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        markdown_text = " ".join(m.value for m in at.markdown)
        assert "ENABLED" in markdown_text
