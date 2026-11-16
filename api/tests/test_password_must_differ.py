"""A forced (first-login) password change cannot keep the temporary password, and a voluntary change cannot keep the current one.

Regression: /me/force-change-password never compared the new password with the current one, so the "forced" change could end with the
same temporary password and still clear must_change_password."""
import pytest

from conftest import create_user, delete_user, login, auth_headers

NEW = "Brand-New#Pass42"


@pytest.fixture
def must_change_user(app):
    from extensions import db
    from models.user import User
    uid, email, pw = create_user(app)
    u = db.session.get(User, uid)
    u.must_change_password = True
    db.session.commit()
    yield uid, email, pw
    delete_user(app, uid)


def _force(client, token, new_password):
    return client.post("/api/auth/me/force-change-password", json={"new_password": new_password},
                       headers=auth_headers(token), content_type="application/json")


def test_forced_change_refuses_the_temporary_password(app, client, must_change_user):
    from extensions import db
    from models.user import User
    uid, email, pw = must_change_user
    token = login(client, email, pw).get_json()["access_token"]
    r = _force(client, token, pw)
    assert r.status_code == 400 and "different from your temporary password" in r.get_json()["error"]
    db.session.expire_all()
    assert db.session.get(User, uid).must_change_password is True        # still forced
    assert login(client, email, pw).status_code == 200                      # nothing changed


def test_forced_change_to_a_new_password_works_and_retires_the_old_one(app, client, must_change_user):
    from extensions import db
    from models.user import User
    uid, email, pw = must_change_user
    token = login(client, email, pw).get_json()["access_token"]
    assert _force(client, token, NEW).status_code == 200
    db.session.expire_all()
    assert db.session.get(User, uid).must_change_password is False
    assert login(client, email, pw).status_code == 401                      # the temporary password no longer works
    assert login(client, email, NEW).status_code == 200


def test_forced_change_is_refused_when_not_required(app, client):
    uid, email, pw = create_user(app)
    try:
        token = login(client, email, pw).get_json()["access_token"]
        assert _force(client, token, NEW).status_code == 403
    finally:
        delete_user(app, uid)


def test_voluntary_change_refuses_the_same_password(app, client):
    uid, email, pw = create_user(app)
    try:
        token = login(client, email, pw).get_json()["access_token"]
        r = client.put("/api/auth/me/password", json={"current_password": pw, "new_password": pw},
                       headers=auth_headers(token), content_type="application/json")
        assert r.status_code == 400 and "different from your current password" in r.get_json()["error"]
        assert login(client, email, pw).status_code == 200
    finally:
        delete_user(app, uid)


def test_voluntary_change_to_a_new_password_still_works(app, client):
    uid, email, pw = create_user(app)
    try:
        token = login(client, email, pw).get_json()["access_token"]
        r = client.put("/api/auth/me/password", json={"current_password": pw, "new_password": NEW},
                       headers=auth_headers(token), content_type="application/json")
        assert r.status_code == 200
        assert login(client, email, NEW).status_code == 200
    finally:
        delete_user(app, uid)
