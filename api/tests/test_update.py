"""Agent auto-update endpoint tests (audits/testing_audit.md Finding C2 —
update.py had zero test coverage before, measured at 25%). Uses monkeypatch
for LATEST_AGENT_VERSION/AGENT_UPDATE_PATH env vars and a real small temp
file for the SHA-256/download-path tests, rather than skipping them."""
import hashlib
import uuid
from conftest import create_user, delete_user, login, auth_headers


def _make_agent_token(app, device_id, raw_token="raw-update-token-for-tests"):
    from extensions import db
    from models.audit import AgentToken
    at = AgentToken(device_id=device_id, token_hash=hashlib.sha256(raw_token.encode()).hexdigest())
    db.session.add(at)
    db.session.commit()
    return raw_token


def _make_device(app):
    from extensions import db
    from models.device import Device
    d = Device(hostname=f"host-{uuid.uuid4().hex[:6]}", platform="windows", is_online=True)
    db.session.add(d)
    db.session.commit()
    return d


def _cleanup(app, *, device_id=None, user_id=None):
    from extensions import db
    from models.device import Device
    from models.audit import AgentToken
    if device_id:
        AgentToken.query.filter_by(device_id=device_id).delete()
        Device.query.filter_by(id=device_id).delete()
    db.session.commit()
    if user_id:
        delete_user(app, user_id)


class TestUpdateInfo:
    def test_requires_auth(self, client):
        r = client.get("/api/agents/update/info")
        assert r.status_code == 401

    def test_no_download_when_path_unset(self, app, client, monkeypatch):
        monkeypatch.delenv("AGENT_UPDATE_PATH", raising=False)
        monkeypatch.setenv("LATEST_AGENT_VERSION", "2.5.0")
        uid, email, pw = create_user(app)
        try:
            token = login(client, email, pw).get_json()["access_token"]
            r = client.get("/api/agents/update/info", headers=auth_headers(token))
            assert r.status_code == 200
            body = r.get_json()
            assert body["latest_version"] == "2.5.0"
            assert body["download_available"] is False
            assert body["checksum_sha256"] is None
        finally:
            _cleanup(app, user_id=uid)

    def test_download_available_when_file_exists(self, app, client, monkeypatch, tmp_path):
        pkg = tmp_path / "agent_update.zip"
        pkg.write_bytes(b"fake agent package contents")
        monkeypatch.setenv("AGENT_UPDATE_PATH", str(pkg))
        monkeypatch.setenv("LATEST_AGENT_VERSION", "3.0.0")
        uid, email, pw = create_user(app)
        try:
            token = login(client, email, pw).get_json()["access_token"]
            r = client.get("/api/agents/update/info", headers=auth_headers(token))
            assert r.status_code == 200
            body = r.get_json()
            assert body["download_available"] is True
            assert body["checksum_sha256"] == hashlib.sha256(pkg.read_bytes()).hexdigest()
        finally:
            _cleanup(app, user_id=uid)


class TestAgentCheck:
    def test_requires_agent_token(self, client):
        r = client.get("/api/agents/update/check?version=1.0.0")
        assert r.status_code == 401

    def test_no_update_when_versions_match(self, app, client, monkeypatch):
        monkeypatch.setenv("LATEST_AGENT_VERSION", "1.0.0")
        monkeypatch.delenv("AGENT_UPDATE_PATH", raising=False)
        dev = _make_device(app)
        try:
            raw_token = _make_agent_token(app, dev.id)
            r = client.get(
                "/api/agents/update/check?version=1.0.0",
                headers={"Authorization": f"Bearer {raw_token}"},
            )
            assert r.status_code == 200
            body = r.get_json()
            assert body["update_available"] is False
            assert body["download_url"] is None
        finally:
            _cleanup(app, device_id=dev.id)

    def test_update_available_when_newer_version_and_file_present(self, app, client, monkeypatch, tmp_path):
        pkg = tmp_path / "agent_update.zip"
        pkg.write_bytes(b"newer package")
        monkeypatch.setenv("AGENT_UPDATE_PATH", str(pkg))
        monkeypatch.setenv("LATEST_AGENT_VERSION", "2.0.0")
        dev = _make_device(app)
        try:
            raw_token = _make_agent_token(app, dev.id)
            r = client.get(
                "/api/agents/update/check?version=1.0.0",
                headers={"Authorization": f"Bearer {raw_token}"},
            )
            assert r.status_code == 200
            body = r.get_json()
            assert body["update_available"] is True
            assert body["download_url"] is not None
            assert body["download_url"].endswith("/api/agents/update/download")
        finally:
            _cleanup(app, device_id=dev.id)

    def test_no_update_available_without_file_even_if_newer(self, app, client, monkeypatch):
        monkeypatch.delenv("AGENT_UPDATE_PATH", raising=False)
        monkeypatch.setenv("LATEST_AGENT_VERSION", "9.9.9")
        dev = _make_device(app)
        try:
            raw_token = _make_agent_token(app, dev.id)
            r = client.get(
                "/api/agents/update/check?version=1.0.0",
                headers={"Authorization": f"Bearer {raw_token}"},
            )
            assert r.status_code == 200
            body = r.get_json()
            # Version comparison says an update exists, but no file is available to serve.
            assert body["update_available"] is True
            assert body["download_url"] is None


        finally:
            _cleanup(app, device_id=dev.id)


class TestAgentDownload:
    def test_requires_agent_token(self, client):
        r = client.get("/api/agents/update/download")
        assert r.status_code == 401

    def test_503_when_no_package_configured(self, app, client, monkeypatch):
        monkeypatch.delenv("AGENT_UPDATE_PATH", raising=False)
        dev = _make_device(app)
        try:
            raw_token = _make_agent_token(app, dev.id)
            r = client.get(
                "/api/agents/update/download",
                headers={"Authorization": f"Bearer {raw_token}"},
            )
            assert r.status_code == 503
        finally:
            _cleanup(app, device_id=dev.id)

    def test_streams_the_real_file(self, app, client, monkeypatch, tmp_path):
        pkg = tmp_path / "agent_update.zip"
        content = b"streamed agent package bytes"
        pkg.write_bytes(content)
        monkeypatch.setenv("AGENT_UPDATE_PATH", str(pkg))
        dev = _make_device(app)
        try:
            raw_token = _make_agent_token(app, dev.id)
            r = client.get(
                "/api/agents/update/download",
                headers={"Authorization": f"Bearer {raw_token}"},
            )
            assert r.status_code == 200
            assert r.data == content
            assert r.headers.get("Content-Length") == str(len(content))
        finally:
            _cleanup(app, device_id=dev.id)


class TestExpiredAgentToken:
    def test_expired_token_rejected(self, app, client):
        from datetime import datetime, timedelta, timezone
        from extensions import db
        from models.audit import AgentToken
        with app.app_context():
            d = _make_device(app)
            raw = _make_agent_token(app, d.id, "expired-token-for-tests")
            AgentToken.query.filter_by(device_id=d.id).update(
                {"expires_at": datetime.now(timezone.utc) - timedelta(days=1)})
            db.session.commit()
            r = client.get("/api/agents/update/check?version=0.0.1", headers=auth_headers(raw))
            _cleanup(app, device_id=d.id)
        assert r.status_code == 401


class TestSseRefreshTokenRejected:
    def test_refresh_token_not_accepted(self, app, client):
        with app.app_context():
            uid, email, pw = create_user(app, role="admin")
            refresh = login(client, email, pw).get_json()["refresh_token"]
            r = client.get(f"/api/events/stream?token={refresh}")
            delete_user(app, uid)
        assert r.status_code == 401
