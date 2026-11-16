"""REPORTS_INLINE=1 builds a report inside the request (for installs without a Celery worker, like the hosted demo).
Off by default: then the task is queued exactly as before."""
import uuid
from unittest.mock import patch

import pytest

from conftest import create_user, delete_user, login, auth_headers


@pytest.fixture
def admin(app):
    uid, email, pw = create_user(app, role="admin")
    yield uid, email, pw
    delete_user(app, uid)


@pytest.fixture
def reports_dir(tmp_path, monkeypatch, app):
    import tasks.report_tasks as rt
    from tasks import _app_singleton
    monkeypatch.setattr(rt, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(_app_singleton, "_app", app)
    return tmp_path


def _generate(client, admin, body=None):
    uid, email, pw = admin
    token = login(client, email, pw).get_json()["access_token"]
    return client.post("/api/reports/generate", headers=auth_headers(token),
                       json=body or {"template_type": "device_health", "name": f"R-{uuid.uuid4().hex[:6]}"})


def _cleanup(app, report_id):
    from extensions import db
    from models.report import Report
    r = db.session.get(Report, report_id)
    if r:
        db.session.delete(r)
        db.session.commit()


def test_inline_mode_builds_the_file_in_the_request(app, client, admin, reports_dir, monkeypatch):
    monkeypatch.setenv("REPORTS_INLINE", "1")
    with patch("tasks.report_tasks.generate_report.delay") as delay:
        r = _generate(client, admin)
    assert r.status_code == 202 and r.get_json()["message"] == "Report generated"
    delay.assert_not_called()
    report_id = r.get_json()["report_id"]
    try:
        from extensions import db
        from models.report import Report
        db.session.expire_all()
        report = db.session.get(Report, report_id)
        assert report.file_path and report.file_path.startswith(str(reports_dir))
        text = open(report.file_path, encoding="utf-8").read()
        assert text.strip(), "the CSV is empty"
        assert report.format == "csv"
    finally:
        _cleanup(app, report_id)


def test_inline_failure_is_a_clear_error_not_a_false_success(app, client, admin, reports_dir, monkeypatch):
    monkeypatch.setenv("REPORTS_INLINE", "1")
    with patch("tasks.report_tasks._collect_data", side_effect=RuntimeError("boom")):
        r = _generate(client, admin)
    assert r.status_code == 500
    assert r.get_json()["error"] == "Report generation failed"
    _cleanup(app, r.get_json()["report_id"])


@pytest.mark.parametrize("value", ["", "0", "false", "no"])
def test_off_by_default_still_queues_the_task(app, client, admin, reports_dir, monkeypatch, value):
    monkeypatch.setenv("REPORTS_INLINE", value)
    with patch("tasks.report_tasks.generate_report.delay") as delay:
        r = _generate(client, admin)
    assert r.status_code == 202 and r.get_json()["message"] == "Report queued"
    delay.assert_called_once_with(r.get_json()["report_id"])
    assert list(reports_dir.iterdir()) == []
    _cleanup(app, r.get_json()["report_id"])
