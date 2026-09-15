"""Auth flow tests — login, lockout, MFA, refresh, password management."""
import pyotp
import pytest
from conftest import create_user, delete_user, login, auth_headers


# ── Login ──────────────────────────────────────────────────────────────────────

class TestLogin:
    def test_success(self, app, client):
        uid, email, pw = create_user(app)
        try:
            r = login(client, email, pw)
            assert r.status_code == 200
            body = r.get_json()
            assert "access_token" in body
            assert "refresh_token" in body
            assert body["user"]["email"] == email
        finally:
            delete_user(app, uid)

    def test_wrong_password(self, app, client):
        uid, email, _ = create_user(app)
        try:
            r = login(client, email, "WrongPass@99!")
            assert r.status_code == 401
            assert "Invalid credentials" in r.get_json()["error"]
        finally:
            delete_user(app, uid)

    def test_unknown_email(self, client):
        r = login(client, "nobody@nowhere.com", "AnyPass@1!")
        assert r.status_code == 401

    def test_missing_fields(self, client):
        r = client.post("/api/auth/login", json={}, content_type="application/json")
        assert r.status_code == 400

    def test_inactive_user(self, app, client):
        uid, email, pw = create_user(app, is_active=False)
        try:
            r = login(client, email, pw)
            assert r.status_code == 401
        finally:
            delete_user(app, uid)

    def test_lockout_after_three_failures(self, app, client):
        uid, email, _ = create_user(app)
        try:
            for _ in range(2):
                r = login(client, email, "BadPass@99!")
                assert r.status_code == 401
            # 3rd attempt triggers lockout
            r = login(client, email, "BadPass@99!")
            assert r.status_code == 423
            body = r.get_json()
            assert body["error"] == "account_locked"
            assert "locked_until" in body
        finally:
            delete_user(app, uid)

    def test_locked_account_rejected_immediately(self, app, client):
        uid, email, pw = create_user(app, is_locked=True)
        try:
            r = login(client, email, pw)
            assert r.status_code == 423
            assert r.get_json()["error"] == "account_locked"
        finally:
            delete_user(app, uid)

    def test_auto_unlock_after_lockout_expiry(self, app, client):
        from datetime import datetime, timezone, timedelta
        from extensions import db
        from models.user import User

        uid, email, pw = create_user(app)
        try:
            # Simulate a lockout that already expired 1 second ago
            u = db.session.get(User, uid)
            u.is_locked = True
            u.failed_login_attempts = 3
            u.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.session.commit()

            r = login(client, email, pw)
            assert r.status_code == 200, f"Expected 200 after auto-unlock, got {r.status_code}"
            assert "access_token" in r.get_json()
        finally:
            delete_user(app, uid)

    def test_correct_password_resets_failed_attempts(self, app, client):
        from extensions import db
        from models.user import User

        uid, email, pw = create_user(app)
        try:
            login(client, email, "BadPass@99!")  # 1 failure
            login(client, email, pw)             # success — should reset counter
            u = db.session.get(User, uid)
            assert u.failed_login_attempts == 0
            assert not u.is_locked
        finally:
            delete_user(app, uid)


# ── MFA ────────────────────────────────────────────────────────────────────────

class TestMFA:
    def _setup_mfa_user(self, app, client):
        """Create user, enable MFA, return (uid, email, pw, secret)."""
        uid, email, pw = create_user(app)
        r = login(client, email, pw)
        tok = r.get_json()["access_token"]

        # Setup MFA — get secret
        r = client.post("/api/auth/mfa/setup", headers=auth_headers(tok))
        assert r.status_code == 200
        secret = r.get_json()["secret"]

        # Enable MFA with valid code
        code = pyotp.TOTP(secret).now()
        r = client.post("/api/auth/mfa/enable",
                        json={"code": code}, headers=auth_headers(tok),
                        content_type="application/json")
        assert r.status_code == 200
        return uid, email, pw, secret

    def test_mfa_login_gate(self, app, client):
        uid, email, pw, secret = self._setup_mfa_user(app, client)
        try:
            r = login(client, email, pw)
            assert r.status_code == 200
            body = r.get_json()
            assert body.get("status") == "mfa_required"
            assert "mfa_token" in body
        finally:
            delete_user(app, uid)

    def test_mfa_login_valid_code(self, app, client):
        uid, email, pw, secret = self._setup_mfa_user(app, client)
        try:
            r = login(client, email, pw)
            mfa_token = r.get_json()["mfa_token"]
            code = pyotp.TOTP(secret).now()
            r2 = client.post("/api/auth/mfa/login",
                             json={"mfa_token": mfa_token, "code": code},
                             content_type="application/json")
            assert r2.status_code == 200
            body = r2.get_json()
            assert "access_token" in body
            assert "refresh_token" in body
        finally:
            delete_user(app, uid)

    def test_mfa_login_invalid_code(self, app, client):
        uid, email, pw, secret = self._setup_mfa_user(app, client)
        try:
            r = login(client, email, pw)
            mfa_token = r.get_json()["mfa_token"]
            r2 = client.post("/api/auth/mfa/login",
                             json={"mfa_token": mfa_token, "code": "000000"},
                             content_type="application/json")
            assert r2.status_code == 401
        finally:
            delete_user(app, uid)

    def test_mfa_login_missing_fields(self, client):
        r = client.post("/api/auth/mfa/login", json={}, content_type="application/json")
        assert r.status_code == 400

    def test_mfa_disable(self, app, client):
        uid, email, pw, secret = self._setup_mfa_user(app, client)
        try:
            r = login(client, email, pw)
            mfa_token = r.get_json()["mfa_token"]
            code = pyotp.TOTP(secret).now()
            r_full = client.post("/api/auth/mfa/login",
                                 json={"mfa_token": mfa_token, "code": code},
                                 content_type="application/json")
            tok = r_full.get_json()["access_token"]

            r_dis = client.post("/api/auth/mfa/disable",
                                json={"password": pw}, headers=auth_headers(tok),
                                content_type="application/json")
            assert r_dis.status_code == 200

            # Now login should return tokens directly, no MFA gate
            r_login = login(client, email, pw)
            assert r_login.status_code == 200
            assert "access_token" in r_login.get_json()
        finally:
            delete_user(app, uid)


# ── Token refresh ──────────────────────────────────────────────────────────────

class TestRefresh:
    def test_refresh_returns_new_access_token(self, app, client):
        uid, email, pw = create_user(app)
        try:
            r = login(client, email, pw)
            refresh_token = r.get_json()["refresh_token"]
            r2 = client.post(
                "/api/auth/refresh",
                headers={"Authorization": f"Bearer {refresh_token}"},
            )
            assert r2.status_code == 200
            assert "access_token" in r2.get_json()
        finally:
            delete_user(app, uid)

    def test_refresh_rejected_without_token(self, client):
        r = client.post("/api/auth/refresh")
        assert r.status_code == 401

    def test_refresh_rejected_with_access_token(self, app, client):
        """Access token must not be accepted as a refresh token."""
        uid, email, pw = create_user(app)
        try:
            r = login(client, email, pw)
            access_token = r.get_json()["access_token"]
            r2 = client.post(
                "/api/auth/refresh",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            assert r2.status_code == 422  # JWT extended returns 422 for wrong token type
        finally:
            delete_user(app, uid)


# ── /me endpoint ───────────────────────────────────────────────────────────────

class TestMe:
    def test_me_requires_auth(self, client):
        r = client.get("/api/auth/me")
        assert r.status_code == 401

    def test_me_returns_current_user(self, app, client):
        uid, email, pw = create_user(app)
        try:
            tok = login(client, email, pw).get_json()["access_token"]
            r = client.get("/api/auth/me", headers=auth_headers(tok))
            assert r.status_code == 200
            body = r.get_json()
            assert body["email"] == email
            assert "password_hash" not in body
        finally:
            delete_user(app, uid)


# ── Password management ────────────────────────────────────────────────────────

class TestPasswordChange:
    def test_change_password_success(self, app, client):
        uid, email, pw = create_user(app)
        try:
            tok = login(client, email, pw).get_json()["access_token"]
            r = client.put(
                "/api/auth/me/password",
                json={"current_password": pw, "new_password": "NewPassword@99!"},
                headers=auth_headers(tok),
                content_type="application/json",
            )
            assert r.status_code == 200
            # Verify new password works
            r2 = login(client, email, "NewPassword@99!")
            assert r2.status_code == 200
        finally:
            delete_user(app, uid)

    def test_change_password_wrong_current(self, app, client):
        uid, email, pw = create_user(app)
        try:
            tok = login(client, email, pw).get_json()["access_token"]
            r = client.put(
                "/api/auth/me/password",
                json={"current_password": "WrongOld@1!", "new_password": "NewPassword@99!"},
                headers=auth_headers(tok),
                content_type="application/json",
            )
            assert r.status_code == 400
        finally:
            delete_user(app, uid)

    def test_change_password_weak_new(self, app, client):
        uid, email, pw = create_user(app)
        try:
            tok = login(client, email, pw).get_json()["access_token"]
            r = client.put(
                "/api/auth/me/password",
                json={"current_password": pw, "new_password": "weak"},
                headers=auth_headers(tok),
                content_type="application/json",
            )
            assert r.status_code == 400
        finally:
            delete_user(app, uid)

    def test_force_change_password(self, app, client):
        from extensions import db
        from models.user import User
        uid, email, pw = create_user(app)
        # Endpoint requires must_change_password=True
        with app.app_context():
            u = db.session.get(User, uid)
            u.must_change_password = True
            db.session.commit()
        try:
            tok = login(client, email, pw).get_json()["access_token"]
            r = client.post(
                "/api/auth/me/force-change-password",
                json={"new_password": "ForceNew@99!"},
                headers=auth_headers(tok),
                content_type="application/json",
            )
            assert r.status_code == 200
        finally:
            delete_user(app, uid)

    def test_force_change_password_weak(self, app, client):
        from extensions import db
        from models.user import User
        uid, email, pw = create_user(app)
        with app.app_context():
            u = db.session.get(User, uid)
            u.must_change_password = True
            db.session.commit()
        try:
            tok = login(client, email, pw).get_json()["access_token"]
            r = client.post(
                "/api/auth/me/force-change-password",
                json={"new_password": "short"},
                headers=auth_headers(tok),
                content_type="application/json",
            )
            assert r.status_code == 400
        finally:
            delete_user(app, uid)


# ── Logout ─────────────────────────────────────────────────────────────────────

class TestLogout:
    def test_logout_success(self, app, client):
        uid, email, pw = create_user(app)
        try:
            tok = login(client, email, pw).get_json()["access_token"]
            r = client.post("/api/auth/logout", headers=auth_headers(tok))
            assert r.status_code == 200
        finally:
            delete_user(app, uid)

    def test_logout_requires_auth(self, client):
        r = client.post("/api/auth/logout")
        assert r.status_code == 401


# ── Password reset ─────────────────────────────────────────────────────────────

class TestPasswordReset:
    def test_reset_request_always_200(self, client):
        """Must return 200 even for unknown email (prevent enumeration)."""
        r = client.post(
            "/api/auth/password-reset/request",
            json={"email": "unknown@nowhere.com"},
            content_type="application/json",
        )
        assert r.status_code == 200

    def test_reset_confirm_invalid_token(self, client):
        r = client.post(
            "/api/auth/password-reset/confirm",
            json={"token": "not-a-real-token", "new_password": "NewPass@99!"},
            content_type="application/json",
        )
        assert r.status_code == 400

    def test_reset_confirm_missing_fields(self, client):
        r = client.post(
            "/api/auth/password-reset/confirm",
            json={},
            content_type="application/json",
        )
        assert r.status_code == 400
