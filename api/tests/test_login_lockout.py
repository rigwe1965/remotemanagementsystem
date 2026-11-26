"""Sign-in lockout is per address, so a stranger cannot lock the real user out (utils/login_guard.py), and the visitor's address
is used when the API sits behind a proxy (utils/client_ip.py)."""
from datetime import datetime, timedelta, timezone

import pytest
from flask import Flask, request

from conftest import create_user, delete_user

OWNER_IP = "198.51.100.10"
ATTACKER_IP = "203.0.113.66"


def login(client, email, password, ip):
    return client.post("/api/auth/login", json={"email": email, "password": password},
                       environ_base={"REMOTE_ADDR": ip})


def _add_audit(user_id, action, ip, minutes_ago=0):
    from extensions import db
    from models.audit import AuditLog
    db.session.add(AuditLog(user_id=user_id, action=action, resource_type="user", ip_address=ip,
                            created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)))
    db.session.commit()


@pytest.fixture
def user(app):
    uid, email, pw = create_user(app)
    yield uid, email, pw
    delete_user(app, uid)


class TestPerAddressLockout:
    def test_strangers_wrong_guesses_do_not_lock_out_the_owner(self, client, user):
        uid, email, pw = user
        for _ in range(2):
            assert login(client, email, "Wrong@Guess1", ATTACKER_IP).status_code == 401
        assert login(client, email, "Wrong@Guess1", ATTACKER_IP).status_code == 423   # the attacker's address is locked ...
        r = login(client, email, pw, OWNER_IP)                                           # ... the owner, elsewhere, signs in
        assert r.status_code == 200 and "access_token" in r.get_json()

    def test_locked_address_is_refused_even_with_the_right_password(self, client, user):
        uid, email, pw = user
        for _ in range(3):
            login(client, email, "Wrong@Guess1", ATTACKER_IP)
        r = login(client, email, pw, ATTACKER_IP)
        assert r.status_code == 423 and r.get_json()["error"] == "account_locked"
        assert "locked_until" in r.get_json()

    def test_lock_ends_after_five_minutes(self, app, client, user):
        from extensions import db
        from models.audit import AuditLog
        uid, email, pw = user
        for _ in range(3):
            login(client, email, "Wrong@Guess1", ATTACKER_IP)
        assert login(client, email, pw, ATTACKER_IP).status_code == 423
        old = datetime.now(timezone.utc) - timedelta(minutes=6)
        AuditLog.query.filter_by(user_id=uid, action="login_failed").update({"created_at": old})
        db.session.commit()
        assert login(client, email, pw, ATTACKER_IP).status_code == 200

    def test_a_good_sign_in_resets_the_count_for_that_address(self, client, user):
        uid, email, pw = user
        for _ in range(2):
            login(client, email, "Wrong@Guess1", OWNER_IP)
        assert login(client, email, pw, OWNER_IP).status_code == 200
        for _ in range(2):                                      # two more wrong ones: still not locked (count restarted)
            assert login(client, email, "Wrong@Guess1", OWNER_IP).status_code == 401

    def test_admin_unlock_clears_every_address(self, app, client, user):
        from extensions import db
        from utils import login_guard
        uid, email, pw = user
        for _ in range(3):
            login(client, email, "Wrong@Guess1", ATTACKER_IP)
        assert login(client, email, pw, ATTACKER_IP).status_code == 423
        login_guard.record_unlock(uid, OWNER_IP)
        db.session.commit()
        assert login(client, email, pw, ATTACKER_IP).status_code == 200

    def test_wrong_two_step_codes_count_too(self, app, user):
        from extensions import db
        from models.user import User
        from utils import login_guard
        uid, email, pw = user
        for _ in range(3):
            _add_audit(uid, "mfa_failed", ATTACKER_IP)
        u = db.session.get(User, uid)
        assert login_guard.locked_until(u, ATTACKER_IP) is not None
        assert login_guard.locked_until(u, OWNER_IP) is None

    def test_the_old_whole_account_flag_is_still_honoured(self, app, client):
        uid, email, pw = create_user(app, is_locked=True)
        try:
            assert login(client, email, pw, OWNER_IP).status_code == 423
        finally:
            delete_user(app, uid)


class TestWideGuessing:
    def test_many_failures_from_unfamiliar_addresses_lock_unfamiliar_addresses_only(self, app, client, user):
        from extensions import db
        from models.user import User
        uid, email, pw = user
        u = db.session.get(User, uid)
        u.known_ips = [OWNER_IP]
        db.session.commit()
        for i in range(30):                                     # a distributed guess: 30 different addresses, one failure each
            _add_audit(uid, "login_failed", f"192.0.2.{i + 1}")
        stranger = "192.0.2.200"
        assert login(client, email, pw, stranger).status_code == 423      # an unfamiliar address is refused, even with the right password
        assert login(client, email, pw, OWNER_IP).status_code == 200      # the owner's familiar address is never caught by this rule

    def test_a_few_failures_from_unfamiliar_addresses_lock_nothing(self, app, client, user):
        uid, email, pw = user
        for i in range(10):
            _add_audit(uid, "login_failed", f"192.0.2.{i + 1}")
        assert login(client, email, pw, "192.0.2.200").status_code == 200


class TestProxyAddress:
    def _app(self, count):
        from utils.client_ip import apply_proxy_fix
        a = Flask(__name__)

        @a.route("/ip")
        def ip():
            return request.remote_addr or ""

        return apply_proxy_fix(a, count)

    def _get(self, count, xff=None, peer="172.18.0.5"):
        h = {"X-Forwarded-For": xff} if xff else {}
        return self._app(count).test_client().get("/ip", headers=h, environ_base={"REMOTE_ADDR": peer}).get_data(as_text=True)

    def test_default_changes_nothing(self):
        assert self._get(0, "9.9.9.9") == "172.18.0.5"

    def test_one_proxy_uses_the_value_it_appended(self):
        assert self._get(1, "9.9.9.9") == "9.9.9.9"

    def test_a_client_supplied_earlier_value_cannot_win(self):
        assert self._get(1, "1.1.1.1, 9.9.9.9") == "9.9.9.9"

    def test_header_shorter_than_the_count_is_ignored(self):
        assert self._get(2, "9.9.9.9") == "172.18.0.5"

    def test_no_header_keeps_the_connecting_address(self):
        assert self._get(1) == "172.18.0.5"

    @pytest.mark.parametrize("raw,expected", [("1", 1), ("0", 0), ("", 0), ("abc", 0), ("-3", 0), ("99", 5), (" 2 ", 2)])
    def test_count_is_read_defensively(self, raw, expected):
        from utils.client_ip import trusted_proxy_count
        assert trusted_proxy_count({"TRUSTED_PROXY_COUNT": raw}) == expected
