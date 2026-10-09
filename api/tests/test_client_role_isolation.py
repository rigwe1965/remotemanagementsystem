"""Regression tests: client-role JWTs must not read staff-only / cross-tenant data."""
import uuid
import pytest
from conftest import create_user, delete_user, login, auth_headers

STAFF_ONLY_GETS = [
    "/api/scripts/runs",
    "/api/patches/",
    "/api/patches/pending",
    "/api/patches/summary",
    "/api/patches/policies",
    "/api/alerts",
    "/api/automation/runs",
    "/api/reports/",
    "/api/reports/templates",
    "/api/customers/",
    "/api/events/recent",
]


@pytest.fixture
def client_token(app, client):
    from extensions import db
    from models.customer import Customer
    from models.user import User
    with app.app_context():
        cust = Customer(name=f"C-{uuid.uuid4().hex[:6]}", slug=uuid.uuid4().hex[:8])
        db.session.add(cust)
        db.session.commit()
        uid, email, pw = create_user(app, role="client")
        db.session.get(User, uid).customer_id = cust.id
        db.session.commit()
        tok = login(client, email, pw).get_json()["access_token"]
        other = Customer(name=f"O-{uuid.uuid4().hex[:6]}", slug=uuid.uuid4().hex[:8])
        db.session.add(other)
        db.session.commit()
        yield tok, other.id
        delete_user(app, uid)


@pytest.mark.parametrize("path", STAFF_ONLY_GETS)
def test_client_role_blocked_from_staff_endpoints(client, client_token, path):
    tok, _ = client_token
    assert client.get(path, headers=auth_headers(tok)).status_code == 403


def test_client_cannot_read_other_customer(client, client_token):
    tok, other_id = client_token
    for path in (f"/api/customers/{other_id}", f"/api/customers/{other_id}/devices"):
        assert client.get(path, headers=auth_headers(tok)).status_code == 404
