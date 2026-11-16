"""The visitor's address is read safely and sent to the API for sign-in, the two-step code and password-reset requests only."""
from unittest.mock import MagicMock, patch

import pytest

from utils import client_ip
from utils.api_client import RMMClient


class TestVisitorIp:
    def test_one_proxy_uses_the_last_entry(self):
        assert client_ip.visitor_ip(headers={"X-Forwarded-For": "9.9.9.9"}, count=1) == "9.9.9.9"

    def test_two_proxies_skip_the_one_the_gateway_added(self):
        assert client_ip.visitor_ip(headers={"X-Forwarded-For": "9.9.9.9, 172.30.0.2"}, count=2) == "9.9.9.9"

    def test_an_address_the_visitor_made_up_cannot_win(self):
        assert client_ip.visitor_ip(headers={"X-Forwarded-For": "1.1.1.1, 9.9.9.9, 172.30.0.2"}, count=2) == "9.9.9.9"

    def test_header_shorter_than_the_count_gives_nothing(self):
        assert client_ip.visitor_ip(headers={"X-Forwarded-For": "9.9.9.9"}, count=2) is None

    def test_missing_header_gives_nothing(self):
        assert client_ip.visitor_ip(headers={}, count=1) is None

    @pytest.mark.parametrize("bad", ["not-an-ip", "9.9.9.9\r\nX-Evil: 1", "", "999.1.1.1", "<script>"])
    def test_a_value_that_is_not_an_address_is_never_sent(self, bad):
        assert client_ip.visitor_ip(headers={"X-Forwarded-For": bad}, count=1) is None

    def test_ipv6_is_accepted(self):
        assert client_ip.visitor_ip(headers={"X-Forwarded-For": "2001:db8::1"}, count=1) == "2001:db8::1"

    def test_without_proxies_streamlits_own_view_is_used(self):
        assert client_ip.visitor_ip(count=0, direct="198.51.100.4") == "198.51.100.4"

    def test_localhost_gives_nothing(self):
        assert client_ip.visitor_ip(count=0, direct=None) is None

    @pytest.mark.parametrize("raw,expected", [("1", 1), ("0", 0), ("", 0), ("abc", 0), ("-2", 0), ("99", 5)])
    def test_count_is_read_defensively(self, raw, expected):
        assert client_ip.trusted_count({"DASHBOARD_TRUSTED_PROXY_COUNT": raw}) == expected


def _ok_response():
    r = MagicMock(status_code=200)
    r.json.return_value = {"ok": True}
    r.raise_for_status.return_value = None
    return r


@pytest.mark.parametrize("call", [
    lambda: RMMClient.login("a@b.test", "pw"),
    lambda: RMMClient.mfa_login("tok", "123456"),
    lambda: RMMClient.request_password_reset("a@b.test"),
])
def test_sign_in_calls_send_the_visitor_address(call):
    with patch("utils.api_client.forward_headers", return_value={"X-Forwarded-For": "9.9.9.9"}), \
         patch("utils.api_client.requests.post", return_value=_ok_response()) as post:
        call()
    assert post.call_args.kwargs["headers"] == {"X-Forwarded-For": "9.9.9.9"}


def test_other_calls_do_not_send_it():
    with patch("utils.api_client.forward_headers", return_value={"X-Forwarded-For": "9.9.9.9"}), \
         patch("utils.api_client.requests.post", return_value=_ok_response()) as post:
        RMMClient.confirm_password_reset("tok", "New@Password1")
    assert "headers" not in post.call_args.kwargs
