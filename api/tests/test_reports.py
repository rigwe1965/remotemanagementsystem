"""Tests for routes/reports.py — report template listing, generation
trigger, and the admin/superadmin-only api_usage template gate
(audits/testing_audit.md Finding C2)."""
import uuid
from unittest.mock import patch
from conftest import create_user, delete_user, login, auth_headers


def _cleanup(app, *, user_id=None, report_ids=()):
    from extensions import db
    from models.report import Report
    for rid in report_ids:
        Report.query.filter_by(id=rid).delete()
    db.session.commit()
    if user_id:
        delete_user(app, user_id)


class TestListTemplates:
    def test_requires_auth(self, client):
        r = client.get("/api/reports/templates")
        assert r.status_code == 401

    def test_regular_admin_sees_api_usage_template(self, app, client):
        uid, email, pw = create_user(app, role="admin")
        try:
            token = login(client, email, pw).get_json()["access_token"]
            r = client.get("/api/reports/templates", headers=auth_headers(token))
            assert r.status_code == 200
            types = [t["type"] for t in r.get_json()]
            assert "api_usage" in types
            assert "patch_summary" in types
        finally:
            delete_user(app, uid)

    def test_technician_does_not_see_api_usage_template(self, app, client):
        uid, email, pw = create_user(app, role="technician")
        try:
            token = login(client, email, pw).get_json()["access_token"]
            r = client.get("/api/reports/templates", headers=auth_headers(token))
            assert r.status_code == 200
            types = [t["type"] for t in r.get_json()]
            assert "api_usage" not in types
            assert "patch_summary" in types
        finally:
            delete_user(app, uid)

    def test_superadmin_sees_api_usage_template(self, app, client):
        uid, email, pw = create_user(app, role="superadmin")
        try:
            token = login(client, email, pw).get_json()["access_token"]
            r = client.get("/api/reports/templates", headers=auth_headers(token))
            assert r.status_code == 200
            types = [t["type"] for t in r.get_json()]
            assert "api_usage" in types
        finally:
            delete_user(app, uid)


class TestListReports:
    def test_technician_never_sees_api_usage_reports(self, app, client):
        from extensions import db
        from models.report import Report
        tech_uid, tech_email, tech_pw = create_user(app, role="technician")
        sa_uid, _, _ = create_user(app, role="superadmin")
        hidden_report = Report(name="Usage Report", template_type="api_usage", generated_by=sa_uid)
        db.session.add(hidden_report)
        db.session.commit()
        try:
            token = login(client, tech_email, tech_pw).get_json()["access_token"]
            r = client.get("/api/reports/", headers=auth_headers(token))
            assert r.status_code == 200
            ids = [rep["id"] for rep in r.get_json()]
            assert hidden_report.id not in ids
        finally:
            _cleanup(app, report_ids=[hidden_report.id])
            delete_user(app, tech_uid)
            delete_user(app, sa_uid)

    def test_admin_sees_api_usage_reports(self, app, client):
        from extensions import db
        from models.report import Report
        admin_uid, admin_email, admin_pw = create_user(app, role="admin")
        sa_uid, _, _ = create_user(app, role="superadmin")
        visible_report = Report(name="Usage Report", template_type="api_usage", generated_by=sa_uid)
        db.session.add(visible_report)
        db.session.commit()
        try:
            token = login(client, admin_email, admin_pw).get_json()["access_token"]
            r = client.get("/api/reports/", headers=auth_headers(token))
            assert r.status_code == 200
            ids = [rep["id"] for rep in r.get_json()]
            assert visible_report.id in ids
        finally:
            _cleanup(app, report_ids=[visible_report.id])
            delete_user(app, admin_uid)
            delete_user(app, sa_uid)


class TestGenerateReport:
    def test_requires_template_type(self, app, client):
        uid, email, pw = create_user(app, role="admin")
        try:
            token = login(client, email, pw).get_json()["access_token"]
            r = client.post("/api/reports/generate", headers=auth_headers(token), json={})
            assert r.status_code == 400
        finally:
            delete_user(app, uid)

    def test_regular_admin_can_request_api_usage_report(self, app, client):
        uid, email, pw = create_user(app, role="admin")
        report_id = None
        try:
            token = login(client, email, pw).get_json()["access_token"]
            with patch("tasks.report_tasks.generate_report.delay"):
                r = client.post("/api/reports/generate", headers=auth_headers(token),
                                 json={"template_type": "api_usage"})
            assert r.status_code == 202
            report_id = r.get_json()["report_id"]
        finally:
            _cleanup(app, user_id=uid, report_ids=[report_id] if report_id else [])

    def test_technician_cannot_request_api_usage_report(self, app, client):
        uid, email, pw = create_user(app, role="technician")
        try:
            token = login(client, email, pw).get_json()["access_token"]
            r = client.post("/api/reports/generate", headers=auth_headers(token),
                             json={"template_type": "api_usage"})
            assert r.status_code == 403
        finally:
            delete_user(app, uid)

    def test_queues_generation_task_and_creates_row(self, app, client):
        uid, email, pw = create_user(app, role="admin")
        report_id = None
        try:
            token = login(client, email, pw).get_json()["access_token"]
            with patch("tasks.report_tasks.generate_report.delay") as mock_delay:
                r = client.post("/api/reports/generate", headers=auth_headers(token),
                                 json={"template_type": "patch_summary", "name": f"R-{uuid.uuid4().hex[:6]}"})
            assert r.status_code == 202
            report_id = r.get_json()["report_id"]
            mock_delay.assert_called_once_with(report_id)

            from models.report import Report
            from extensions import db
            report = db.session.get(Report, report_id)
            assert report is not None
            assert report.template_type == "patch_summary"
            assert report.generated_by == uid
        finally:
            _cleanup(app, user_id=uid, report_ids=[report_id] if report_id else [])


class TestGetReport:
    def test_404_for_unknown_report(self, app, client):
        uid, email, pw = create_user(app, role="admin")
        try:
            token = login(client, email, pw).get_json()["access_token"]
            r = client.get("/api/reports/not-a-real-id", headers=auth_headers(token))
            assert r.status_code == 404
        finally:
            delete_user(app, uid)

    def test_regular_admin_can_view_api_usage_report(self, app, client):
        from extensions import db
        from models.report import Report
        admin_uid, admin_email, admin_pw = create_user(app, role="admin")
        sa_uid, _, _ = create_user(app, role="superadmin")
        report = Report(name="Usage Report", template_type="api_usage", generated_by=sa_uid)
        db.session.add(report)
        db.session.commit()
        try:
            token = login(client, admin_email, admin_pw).get_json()["access_token"]
            r = client.get(f"/api/reports/{report.id}", headers=auth_headers(token))
            assert r.status_code == 200
        finally:
            _cleanup(app, report_ids=[report.id])
            delete_user(app, admin_uid)
            delete_user(app, sa_uid)

    def test_technician_forbidden_from_api_usage_report(self, app, client):
        from extensions import db
        from models.report import Report
        tech_uid, tech_email, tech_pw = create_user(app, role="technician")
        sa_uid, _, _ = create_user(app, role="superadmin")
        report = Report(name="Usage Report", template_type="api_usage", generated_by=sa_uid)
        db.session.add(report)
        db.session.commit()
        try:
            token = login(client, tech_email, tech_pw).get_json()["access_token"]
            r = client.get(f"/api/reports/{report.id}", headers=auth_headers(token))
            assert r.status_code == 403
        finally:
            _cleanup(app, report_ids=[report.id])
            delete_user(app, tech_uid)
            delete_user(app, sa_uid)
