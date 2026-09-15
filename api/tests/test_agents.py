"""Agent registration, heartbeat, token expiry, and rotation tests."""
import hashlib
import uuid
from datetime import datetime, timezone, timedelta

import pytest
from conftest import create_user, delete_user, login, auth_headers


ORG_TOKEN = "test-org-token-unique-secret-value"  # matches conftest setdefault


def _reg_payload(**overrides):
    """Default valid registration payload."""
    base = {
        "org_token": ORG_TOKEN,
        "hostname": f"HOST-{uuid.uuid4().hex[:6].upper()}",
        "mac_address": "AA:BB:CC:DD:EE:FF",
        "serial_number": "SN123456",
        "platform": "windows",
        "os_name": "Windows 11",
        "os_version": "23H2",
        "cpu_model": "Intel i7",
        "cpu_cores": 8,
        "ram_gb": 16,
        "agent_version": "1.0.0",
    }
    base.update(overrides)
    return base


def _register(client, **overrides):
    """POST /api/agents/register and return response."""
    return client.post(
        "/api/agents/register",
        json=_reg_payload(**overrides),
        content_type="application/json",
    )


def _heartbeat(client, device_id, agent_token, metrics=None):
    payload = metrics or {"cpu_pct": 10, "ram_pct": 20, "disk_pct": 30}
    return client.post(
        f"/api/agents/{device_id}/heartbeat",
        json=payload,
        headers={"Authorization": f"Bearer {agent_token}"},
        content_type="application/json",
    )


# ── Registration ───────────────────────────────────────────────────────────────

class TestAgentRegister:
    def test_register_success(self, client, customer):
        r = _register(client)
        assert r.status_code == 201
        body = r.get_json()
        assert "device_id" in body
        assert "agent_token" in body

    def test_register_missing_hostname(self, client, customer):
        r = _register(client, hostname="")
        assert r.status_code == 400

    def test_register_bad_org_token(self, client, customer):
        r = _register(client, org_token="wrong-token")
        assert r.status_code == 403

    def test_register_no_customer(self, app, client):
        """Should fail 400 when no active customer exists."""
        from extensions import db
        from models.customer import Customer
        # Deactivate all customers temporarily
        Customer.query.update({"is_active": False})
        db.session.commit()
        try:
            r = _register(client)
            assert r.status_code == 400
        finally:
            Customer.query.update({"is_active": True})
            db.session.commit()

    def test_reregister_revokes_old_token(self, client, customer):
        """Re-registering same fingerprint revokes old token and issues a new one."""
        payload = _reg_payload()
        r1 = client.post("/api/agents/register", json=payload,
                         content_type="application/json")
        assert r1.status_code == 201
        old_token = r1.get_json()["agent_token"]
        device_id = r1.get_json()["device_id"]

        r2 = client.post("/api/agents/register", json=payload,
                         content_type="application/json")
        assert r2.status_code == 201
        new_token = r2.get_json()["agent_token"]
        assert new_token != old_token

        # Old token should now be rejected
        r_hb = _heartbeat(client, device_id, old_token)
        assert r_hb.status_code == 401

    def test_register_sets_expires_at(self, app, client, customer):
        """Issued token must have expires_at ~90 days out."""
        r = _register(client)
        assert r.status_code == 201
        device_id = r.get_json()["device_id"]
        agent_token_raw = r.get_json()["agent_token"]

        from models.audit import AgentToken
        token_hash = hashlib.sha256(agent_token_raw.encode()).hexdigest()
        tok = AgentToken.query.filter_by(device_id=device_id, token_hash=token_hash).first()
        assert tok is not None
        assert tok.expires_at is not None
        exp = tok.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        days = (exp - datetime.now(timezone.utc)).days
        assert 88 <= days <= 91  # ~90 days


# ── Heartbeat ─────────────────────────────────────────────────────────────────

class TestAgentHeartbeat:
    @pytest.fixture
    def registered(self, client, customer):
        """Register an agent and return (device_id, agent_token)."""
        r = _register(client)
        assert r.status_code == 201
        return r.get_json()["device_id"], r.get_json()["agent_token"]

    def test_heartbeat_success(self, client, registered):
        device_id, token = registered
        r = _heartbeat(client, device_id, token)
        assert r.status_code == 200
        assert r.get_json()["status"] == "ok"

    def test_heartbeat_stores_metrics(self, app, client, registered):
        device_id, token = registered
        _heartbeat(client, device_id, token,
                   metrics={"cpu_pct": 55.0, "ram_pct": 60.0, "disk_pct": 40.0})

        from models.device import DeviceMetrics
        m = DeviceMetrics.query.filter_by(device_id=device_id).order_by(
            DeviceMetrics.collected_at.desc()
        ).first()
        assert m is not None
        assert abs(m.cpu_pct - 55.0) < 0.01

    def test_heartbeat_status_healthy(self, app, client, registered):
        device_id, token = registered
        _heartbeat(client, device_id, token,
                   metrics={"cpu_pct": 10, "ram_pct": 20, "disk_pct": 30})
        from extensions import db
        from models.device import Device
        d = db.session.get(Device, device_id)
        assert d.status == "healthy"

    def test_heartbeat_status_warning(self, app, client, registered):
        device_id, token = registered
        _heartbeat(client, device_id, token,
                   metrics={"cpu_pct": 80, "ram_pct": 20, "disk_pct": 30})
        from extensions import db
        from models.device import Device
        d = db.session.get(Device, device_id)
        assert d.status == "warning"

    def test_heartbeat_status_critical(self, app, client, registered):
        device_id, token = registered
        _heartbeat(client, device_id, token,
                   metrics={"cpu_pct": 95, "ram_pct": 20, "disk_pct": 30})
        from extensions import db
        from models.device import Device
        d = db.session.get(Device, device_id)
        assert d.status == "critical"

    def test_heartbeat_updates_last_seen(self, app, client, registered):
        device_id, token = registered
        before = datetime.now(timezone.utc)
        _heartbeat(client, device_id, token)
        from extensions import db
        from models.device import Device
        d = db.session.get(Device, device_id)
        last_seen = d.last_seen
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        assert last_seen >= before
        assert d.is_online is True

    def test_heartbeat_wrong_token(self, client, registered):
        device_id, _ = registered
        r = _heartbeat(client, device_id, "bad-token-value")
        assert r.status_code == 401

    def test_heartbeat_wrong_device_id(self, client, registered):
        _, token = registered
        r = _heartbeat(client, str(uuid.uuid4()), token)
        assert r.status_code == 401

    def test_heartbeat_expired_token(self, app, client, customer):
        """Expired token must be rejected with 401."""
        r = _register(client)
        device_id = r.get_json()["device_id"]
        raw_token = r.get_json()["agent_token"]

        from extensions import db
        from models.audit import AgentToken
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        tok = AgentToken.query.filter_by(device_id=device_id, token_hash=token_hash).first()
        # Backdate expiry to 1 second ago
        tok.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.session.commit()

        r_hb = _heartbeat(client, device_id, raw_token)
        assert r_hb.status_code == 401

    def test_heartbeat_token_rotation_when_near_expiry(self, app, client, customer):
        """Heartbeat returns new_agent_token when token has < 7 days remaining."""
        r = _register(client)
        device_id = r.get_json()["device_id"]
        raw_token = r.get_json()["agent_token"]

        from extensions import db
        from models.audit import AgentToken
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        tok = AgentToken.query.filter_by(device_id=device_id, token_hash=token_hash).first()
        # Set expiry to 3 days from now (< 7-day rotation window)
        tok.expires_at = datetime.now(timezone.utc) + timedelta(days=3)
        db.session.commit()

        r_hb = _heartbeat(client, device_id, raw_token)
        assert r_hb.status_code == 200
        body = r_hb.get_json()
        assert "new_agent_token" in body, "Expected rotation token in response"
        new_token = body["new_agent_token"]
        assert new_token != raw_token

        # Old token should now be revoked
        r_old = _heartbeat(client, device_id, raw_token)
        assert r_old.status_code == 401

        # New token must work
        r_new = _heartbeat(client, device_id, new_token)
        assert r_new.status_code == 200

    def test_heartbeat_no_rotation_when_plenty_of_time(self, app, client, customer):
        """No rotation when token has 30+ days remaining."""
        r = _register(client)
        device_id = r.get_json()["device_id"]
        raw_token = r.get_json()["agent_token"]  # expires in 90 days

        r_hb = _heartbeat(client, device_id, raw_token)
        assert r_hb.status_code == 200
        assert "new_agent_token" not in r_hb.get_json()


# ── Task flow ─────────────────────────────────────────────────────────────────

class TestAgentTasks:
    def test_get_tasks_empty(self, client, customer):
        r = _register(client)
        device_id = r.get_json()["device_id"]
        token = r.get_json()["agent_token"]

        r2 = client.get(
            f"/api/agents/{device_id}/tasks",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r2.status_code == 200
        assert r2.get_json()["tasks"] == []

    def test_get_tasks_unauthorized(self, client, customer):
        r = _register(client)
        device_id = r.get_json()["device_id"]
        r2 = client.get(f"/api/agents/{device_id}/tasks")
        assert r2.status_code == 401

    def test_task_result_accepted(self, client, customer):
        r = _register(client)
        device_id = r.get_json()["device_id"]
        token = r.get_json()["agent_token"]

        r2 = client.post(
            f"/api/agents/{device_id}/task_result",
            json={"task_id": str(uuid.uuid4()), "type": "run_script",
                  "exit_code": 0, "stdout": "ok", "stderr": ""},
            headers={"Authorization": f"Bearer {token}"},
            content_type="application/json",
        )
        assert r2.status_code == 200


# ── Software inventory ────────────────────────────────────────────────────────

class TestAgentSoftware:
    def test_update_software(self, client, customer):
        r = _register(client)
        device_id = r.get_json()["device_id"]
        token = r.get_json()["agent_token"]

        software = [
            {"name": "Notepad++", "version": "8.6", "publisher": "Notepad++ Team"},
            {"name": "7-Zip", "version": "24.01", "publisher": "Igor Pavlov"},
        ]
        r2 = client.put(
            f"/api/agents/{device_id}/software",
            json={"software": software},
            headers={"Authorization": f"Bearer {token}"},
            content_type="application/json",
        )
        assert r2.status_code == 200
        assert r2.get_json()["count"] == 2

    def test_update_software_replaces_previous(self, app, client, customer):
        r = _register(client)
        device_id = r.get_json()["device_id"]
        token = r.get_json()["agent_token"]

        client.put(f"/api/agents/{device_id}/software",
                   json={"software": [{"name": "OldApp", "version": "1.0"}]},
                   headers={"Authorization": f"Bearer {token}"},
                   content_type="application/json")

        client.put(f"/api/agents/{device_id}/software",
                   json={"software": [{"name": "NewApp", "version": "2.0"}]},
                   headers={"Authorization": f"Bearer {token}"},
                   content_type="application/json")

        from models.device import InstalledSoftware
        sw = InstalledSoftware.query.filter_by(device_id=device_id).all()
        names = [s.name for s in sw]
        assert "OldApp" not in names
        assert "NewApp" in names
