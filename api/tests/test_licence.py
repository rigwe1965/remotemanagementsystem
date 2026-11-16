"""Licence check (utils/licence.py): the shared test vectors, and what it does to adding devices and staff accounts.

The vectors in fixtures/licence-test-vectors.json are the contract with the reference implementation in the owner's tooling
(licensing/licence.mjs). Dates in the route tests are built from today's date, so nothing here goes stale.
"""
import base64
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from conftest import auth_headers, create_user, delete_user, login

from utils import licence

VECTORS = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "licence-test-vectors.json"), encoding="utf-8"))
ORG_TOKEN = "test-org-token-unique-secret-value"


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class Issuer:
    """Stands in for the owner's tool: a private key that makes licences the code under test will accept."""

    def __init__(self):
        self.key = Ed25519PrivateKey.generate()
        self.public = _b64u(self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))

    def token(self, **over):
        now = datetime.now(timezone.utc)
        payload = {
            "v": 1, "id": f"lic_{uuid.uuid4().hex[:8]}", "product": "rmm", "customer": "Acme IT", "tier": "premium",
            "iat": (now - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "exp": (now + timedelta(days=200)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limits": {"devices": 250, "users": 25},
        }
        payload.update(over)
        body = "FKL1." + _b64u(json.dumps(payload).encode())
        return f"{body}.{_b64u(self.key.sign(body.encode()))}"


@pytest.fixture
def issuer(monkeypatch):
    i = Issuer()
    monkeypatch.setenv("LICENCE_PUBLIC_KEYS", i.public)
    monkeypatch.delenv("LICENCE_FILE", raising=False)
    monkeypatch.delenv("LICENCE_KEY", raising=False)
    monkeypatch.delenv("LICENCE_ENFORCEMENT", raising=False)
    return i


# ── The shared vectors ──────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("case", VECTORS["verify"], ids=lambda c: c["name"])
def test_vector_verify(case):
    r = licence.verify(case["token"], [VECTORS["publicKey"]], case.get("product"))
    assert r["ok"] == case["expect"]["ok"]
    if not case["expect"]["ok"]:
        assert r["reason"] == case["expect"]["reason"]


@pytest.mark.parametrize("case", VECTORS["evaluate"], ids=lambda c: c["name"])
def test_vector_evaluate(case):
    lic = licence.verify(case["token"], [VECTORS["publicKey"]])["licence"]
    e = licence.evaluate(lic, datetime.fromisoformat(case["now"].replace("Z", "+00:00")), case["usage"])
    for key in ("state", "daysLeft", "endsOn", "graceEndsOn", "canAdd", "over", "banner"):
        assert e[key] == case["expect"][key], key


# ── Reading and checking ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_payload_rules():
    good = {"v": 1, "id": "x", "product": "rmm", "customer": "A", "tier": "t", "iat": "2026-01-01T00:00:00Z",
            "exp": "2027-01-01T00:00:00Z", "limits": {"devices": 5}}
    assert licence.check_payload(good) is good
    for bad in (None, [], {**good, "v": 2}, {**good, "v": True}, {**good, "id": ""}, {**good, "product": "Bad Product"},
                {**good, "iat": "yesterday"}, {**good, "exp": "2025-01-01T00:00:00Z"}, {**good, "limits": None},
                {**good, "limits": {"devices": -1}}, {**good, "limits": {"devices": 1.5}}, {**good, "limits": {"devices": True}},
                {**good, "limits": {"Bad-Name": 1}}):
        with pytest.raises(ValueError):
            licence.check_payload(bad)
    licence.check_payload({**good, "limits": {"devices": None}})  # null means unlimited


def test_a_pasted_licence_with_spaces_still_verifies():
    assert licence.verify(f"  {VECTORS['verify'][0]['token']}\n", [VECTORS["publicKey"]])["ok"]


def test_garbage_keys_never_verify_and_never_raise():
    assert licence.verify(VECTORS["verify"][0]["token"], ["not-a-key", "", "AAAA"])["reason"] == "bad_signature"


def test_rotation_second_key_works(issuer):
    other = Issuer()
    assert licence.verify(issuer.token(), [other.public, issuer.public])["ok"]
    assert licence.verify(issuer.token(), [other.public])["reason"] == "bad_signature"


# ── Off by default ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_nothing_is_checked_unless_enforcement_is_on(app, issuer):
    assert licence.status() == {"enforced": False, "state": "not_enforced", "banner": None}
    assert licence.check_can_add("devices") is None
    assert licence.check_can_add("users") is None


def test_only_the_value_1_turns_it_on(monkeypatch, issuer):
    for v in ("", "0", "true", "yes", "on"):
        monkeypatch.setenv("LICENCE_ENFORCEMENT", v)
        assert licence.enforcement_on() is False
    monkeypatch.setenv("LICENCE_ENFORCEMENT", "1")
    assert licence.enforcement_on() is True


# ── Enforcement on ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def _on(monkeypatch, issuer, **payload):
    monkeypatch.setenv("LICENCE_ENFORCEMENT", "1")
    monkeypatch.setenv("LICENCE_KEY", issuer.token(**payload))


def test_no_licence_means_no_additions_but_a_clear_message(app, monkeypatch, issuer):
    monkeypatch.setenv("LICENCE_ENFORCEMENT", "1")
    with app.test_request_context():
        resp, code = licence.check_can_add("devices")
    assert code == 402 and resp.get_json()["code"] == "LICENCE_REQUIRED"
    assert "keeps working" in resp.get_json()["error"]
    s = licence.status()
    assert s["state"] == "unlicensed" and s["reason"] == "none" and s["banner"]


@pytest.mark.parametrize("label,make", [
    ("signed by someone else", lambda i: Issuer().token()),
    ("for another product", lambda i: i.token(product="reci")),
    ("not a licence", lambda i: "hello"),
])
def test_a_licence_that_is_not_ours_counts_as_none(app, monkeypatch, issuer, label, make):
    monkeypatch.setenv("LICENCE_ENFORCEMENT", "1")
    monkeypatch.setenv("LICENCE_KEY", make(issuer))
    with app.test_request_context():
        resp, code = licence.check_can_add("users")
    assert code == 402 and resp.get_json()["code"] == "LICENCE_REQUIRED"


def test_a_lapsed_licence_blocks_additions_with_its_own_message(app, monkeypatch, issuer):
    now = datetime.now(timezone.utc)
    _on(monkeypatch, issuer, iat=(now - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ"), exp=(now - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    with app.test_request_context():
        resp, code = licence.check_can_add("devices")
    assert code == 402 and resp.get_json()["code"] == "LICENCE_LAPSED"
    assert "Everything you have keeps working" in resp.get_json()["error"]


def test_status_has_customer_and_usage_but_never_the_licence_text(app, monkeypatch, issuer):
    _on(monkeypatch, issuer)
    s = licence.status()
    assert s["enforced"] and s["state"] == "active" and s["customer"] == "Acme IT"
    assert set(s["usage"]) == {"devices", "users"}
    assert "FKL1" not in json.dumps(s) and "signature" not in json.dumps(s).lower()


def test_licence_file_is_reread_when_it_changes(app, monkeypatch, issuer, tmp_path):
    f = tmp_path / "licence.txt"
    f.write_text(issuer.token(customer="First"))
    monkeypatch.setenv("LICENCE_ENFORCEMENT", "1")
    monkeypatch.setenv("LICENCE_FILE", str(f))
    assert licence.status()["customer"] == "First"
    f.write_text(issuer.token(customer="Renewed"))
    os.utime(f, (f.stat().st_atime, f.stat().st_mtime + 5))  # filesystems with coarse timestamps
    assert licence.status()["customer"] == "Renewed"


def test_an_unreadable_licence_file_counts_as_none_and_does_not_raise(app, monkeypatch, issuer, tmp_path):
    monkeypatch.setenv("LICENCE_ENFORCEMENT", "1")
    monkeypatch.setenv("LICENCE_FILE", str(tmp_path / "missing.txt"))
    assert licence.status()["state"] == "unlicensed"


# ── At the three doors ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _admin_token(app, client, role="admin"):
    uid, email, pw = create_user(app, role=role)
    return uid, login(client, email, pw).get_json()["access_token"]


def _new_device(client, token):
    return client.post("/api/devices/", headers=auth_headers(token), json={"hostname": f"PRINTER-{uuid.uuid4().hex[:6]}"})


def _clean_devices(app, hostnames):
    from extensions import db
    from models.device import Device
    from utils.cache import cache_delete_pattern
    for h in hostnames:
        Device.query.filter_by(hostname=h).delete()
    db.session.commit()
    # The device list is cached for 30 seconds; rows removed behind its back must not leave a stale list for the next test or run.
    cache_delete_pattern("rmm:devices:list:*")


def test_a_device_added_by_hand_is_refused_at_the_limit_and_allowed_below_it(app, client, monkeypatch, issuer):
    uid, token = _admin_token(app, client)
    made = []
    try:
        now_used = licence.usage_now()["devices"]
        _on(monkeypatch, issuer, limits={"devices": now_used + 1, "users": 25})
        r = _new_device(client, token)
        assert r.status_code == 201, r.get_json()  # one below the limit: allowed
        made.append(r.get_json()["hostname"])
        r2 = _new_device(client, token)
        assert r2.status_code == 402
        assert r2.get_json()["code"] == "LICENCE_LIMIT"
        assert "all of them are in use" in r2.get_json()["error"]
    finally:
        _clean_devices(app, made)
        delete_user(app, uid)


def test_without_enforcement_the_same_request_is_never_refused(app, client, monkeypatch, issuer):
    uid, token = _admin_token(app, client)
    made = []
    try:
        monkeypatch.setenv("LICENCE_KEY", issuer.token(limits={"devices": 0, "users": 0}))  # a licence is present but ignored
        r = _new_device(client, token)
        assert r.status_code == 201
        made.append(r.get_json()["hostname"])
    finally:
        _clean_devices(app, made)
        delete_user(app, uid)


def test_an_agent_that_is_already_registered_always_gets_through(app, client, customer, monkeypatch, issuer):
    from test_agents import _reg_payload
    payload = _reg_payload()
    made = [payload["hostname"]]
    try:
        assert client.post("/api/agents/register", json=payload).status_code == 201  # before any licence
        _on(monkeypatch, issuer, limits={"devices": 0, "users": 0})  # nothing may be added, and more is in use than covered
        again = client.post("/api/agents/register", json=payload)
        assert again.status_code in (200, 201), again.get_json()  # the same machine reports in as usual
        fresh = client.post("/api/agents/register", json=_reg_payload())
        assert fresh.status_code == 402 and fresh.get_json()["code"] == "LICENCE_LIMIT"  # a different, new machine does not
    finally:
        _clean_devices(app, made)


def test_a_staff_account_is_refused_at_the_limit_but_a_client_portal_account_is_not(app, client, monkeypatch, issuer):
    uid, token = _admin_token(app, client)
    made = []
    try:
        _on(monkeypatch, issuer, limits={"devices": 250, "users": licence.usage_now()["users"]})  # exactly full
        mail = lambda: f"new_{uuid.uuid4().hex[:8]}@test.local"  # noqa: E731
        staff = client.post("/api/admin/users", headers=auth_headers(token), json={"email": mail(), "full_name": "S", "password": "GoodPass@1!", "role": "technician"})
        assert staff.status_code == 402 and staff.get_json()["code"] == "LICENCE_LIMIT"
        from extensions import db
        from models.customer import Customer
        cust = Customer(name="C", slug=f"c-{uuid.uuid4().hex[:6]}", is_active=True)
        db.session.add(cust)
        db.session.commit()
        email = mail()
        portal = client.post("/api/admin/users", headers=auth_headers(token), json={"email": email, "full_name": "P", "password": "GoodPass@1!", "role": "client", "customer_id": cust.id})
        assert portal.status_code == 201, portal.get_json()
        made.append(email)
    finally:
        from extensions import db
        from models.user import User
        for e in made:
            u = User.query.filter_by(email=e).first()
            if u:
                delete_user(app, u.id)
        db.session.commit()
        delete_user(app, uid)


def test_existing_people_can_still_sign_in_when_over_the_limit(app, client, monkeypatch, issuer):
    uid, email, pw = create_user(app, role="admin")
    try:
        _on(monkeypatch, issuer, limits={"devices": 0, "users": 0})  # far over
        r = login(client, email, pw)
        assert r.status_code == 200 and "access_token" in r.get_json()
        token = r.get_json()["access_token"]
        assert client.get("/api/devices/", headers=auth_headers(token)).status_code == 200  # reading is untouched
    finally:
        from utils.cache import cache_delete_pattern
        cache_delete_pattern("rmm:devices:list:*")  # that read cached an (empty) list for 30 s; do not leave it for other tests
        delete_user(app, uid)


# ── The status endpoint ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_status_endpoint_is_for_admins_only(app, client, monkeypatch, issuer):
    assert client.get("/api/admin/licence/status").status_code == 401
    t_uid, tech = _admin_token(app, client, role="technician")
    a_uid, admin = _admin_token(app, client, role="admin")
    try:
        assert client.get("/api/admin/licence/status", headers=auth_headers(tech)).status_code == 403
        r = client.get("/api/admin/licence/status", headers=auth_headers(admin))
        assert r.status_code == 200 and r.get_json() == {"enforced": False, "state": "not_enforced", "banner": None}
        _on(monkeypatch, issuer)
        s = client.get("/api/admin/licence/status", headers=auth_headers(admin)).get_json()
        assert s["enforced"] and s["state"] == "active" and s["customer"] == "Acme IT" and s["banner"] is None
    finally:
        delete_user(app, t_uid)
        delete_user(app, a_uid)
