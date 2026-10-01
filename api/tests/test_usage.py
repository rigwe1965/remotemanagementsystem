"""Tests for API/Token Usage Monitoring: RBAC, event recording + cost calc,
anomaly detection, hourly rollup persistence, and retention pruning."""
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest
from conftest import create_user, delete_user, login, auth_headers


def _auth_token(app, client, role):
    uid, email, pw = create_user(app, role=role)
    token = login(client, email, pw).get_json()["access_token"]
    return uid, token


# ── RBAC — admin and superadmin only ────────────────────────────────────────────

class TestUsageRBAC:
    _GET_ROUTES = [
        "/api/admin/usage/summary",
        "/api/admin/usage/timeseries",
        "/api/admin/usage/by-feature",
        "/api/admin/usage/events",
        "/api/admin/usage/alert-config",
    ]

    def test_admin_gets_200_on_every_route(self, app, client):
        uid, token = _auth_token(app, client, "admin")
        try:
            for path in self._GET_ROUTES:
                resp = client.get(path, headers=auth_headers(token))
                assert resp.status_code == 200, f"GET {path} should be 200 for admin: {resp.get_json()}"
        finally:
            delete_user(app, uid)

    def test_technician_gets_403(self, app, client):
        uid, token = _auth_token(app, client, "technician")
        try:
            resp = client.get("/api/admin/usage/summary", headers=auth_headers(token))
            assert resp.status_code == 403
        finally:
            delete_user(app, uid)

    def test_superadmin_gets_200_on_every_route(self, app, client):
        uid, token = _auth_token(app, client, "superadmin")
        try:
            for path in self._GET_ROUTES:
                resp = client.get(path, headers=auth_headers(token))
                assert resp.status_code == 200, f"GET {path} should be 200 for superadmin: {resp.get_json()}"
        finally:
            delete_user(app, uid)

    def test_admin_can_update_alert_config(self, app, client):
        uid, token = _auth_token(app, client, "admin")
        try:
            resp = client.put("/api/admin/usage/alert-config", json={"is_enabled": True},
                               headers=auth_headers(token))
            assert resp.status_code == 200
        finally:
            delete_user(app, uid)

    def test_superadmin_can_update_alert_config(self, app, client):
        uid, token = _auth_token(app, client, "superadmin")
        try:
            resp = client.put("/api/admin/usage/alert-config",
                               json={"is_enabled": True, "spike_multiplier": 2.5,
                                     "notification_channels": {"email": ["ops@test.local"]}},
                               headers=auth_headers(token))
            assert resp.status_code == 200
            body = resp.get_json()
            assert body["is_enabled"] is True
            assert body["spike_multiplier"] == 2.5
            assert body["notification_channels"]["email"] == ["ops@test.local"]
        finally:
            delete_user(app, uid)


# ── record_event + cost calculation ─────────────────────────────────────────────

class TestRecordEvent:
    def test_writes_event_with_computed_cost(self, app, monkeypatch):
        monkeypatch.setenv("AI_ASSISTANT_MODEL", "claude-haiku-4-5-20251001")
        monkeypatch.setenv("AI_ASSISTANT_COST_PER_1M_INPUT", "1.00")
        monkeypatch.setenv("AI_ASSISTANT_COST_PER_1M_OUTPUT", "5.00")

        with app.app_context():
            # Re-import fresh so the monkeypatched env vars are picked up by the
            # module-level pricing table (built at import time).
            import importlib
            import utils.usage_tracker as ut
            importlib.reload(ut)

            ut.record_event(service="ai_assistant", feature="Overview", input_tokens=1000,
                             output_tokens=2000, status="success", latency_ms=123,
                             model="claude-haiku-4-5-20251001")

            from models.usage import ApiUsageEvent
            row = ApiUsageEvent.query.filter_by(service="ai_assistant", feature="Overview").order_by(
                ApiUsageEvent.id.desc()
            ).first()
            assert row is not None
            assert row.input_tokens == 1000
            assert row.output_tokens == 2000
            expected_cost = (1000 / 1_000_000) * 1.00 + (2000 / 1_000_000) * 5.00
            assert row.estimated_cost_usd == pytest.approx(expected_cost, rel=1e-6)
            assert row.latency_ms == 123
            assert row.status == "success"

    def test_never_raises_on_bad_input(self, app):
        """record_event fails open — a tracking bug must never break the caller."""
        with app.app_context():
            from utils.usage_tracker import record_event
            # Simulate a DB failure at the write site and confirm it's swallowed, not propagated.
            with patch("models.usage.ApiUsageEvent", side_effect=Exception("boom")):
                record_event(service="ai_assistant", feature="x", status="success")  # must not raise

    def test_no_cost_for_unpriced_service(self, app):
        with app.app_context():
            from utils.usage_tracker import record_event
            from models.usage import ApiUsageEvent
            record_event(service="webhook_slack", feature="Test Rule", status="success", latency_ms=50)
            row = ApiUsageEvent.query.filter_by(service="webhook_slack").order_by(
                ApiUsageEvent.id.desc()
            ).first()
            assert row.estimated_cost_usd is None


# ── compute_anomalies ────────────────────────────────────────────────────────────

class TestComputeAnomalies:
    def _hour_start(self, offset_hours=0):
        now = datetime.now(timezone.utc)
        return (now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1 + offset_hours))

    def _insert_events(self, service, hour_start, count):
        from extensions import db
        from models.usage import ApiUsageEvent
        for _ in range(count):
            db.session.add(ApiUsageEvent(service=service, created_at=hour_start + timedelta(minutes=1),
                                          status="success"))
        db.session.commit()

    def test_flags_a_real_spike(self, app):
        with app.app_context():
            from utils.usage_tracker import compute_anomalies
            service = f"stripe"
            current_hour = self._hour_start(0)
            # Baseline: 2 calls/hour for the past 7 days at the same hour-of-day.
            for d in range(1, 8):
                self._insert_events(service, current_hour - timedelta(days=d), 2)
            # Spike: 50 calls in the most recently completed hour.
            self._insert_events(service, current_hour, 50)

            anomalies = compute_anomalies(spike_multiplier=3.0)
            hit = next((a for a in anomalies if a["service"] == service), None)
            assert hit is not None, f"expected a spike flagged for {service}, got {anomalies}"
            assert hit["current_hour_count"] == 50
            assert hit["multiplier"] > 3.0

    def test_no_flag_when_under_multiplier(self, app):
        with app.app_context():
            from utils.usage_tracker import compute_anomalies
            service = "smtp"
            current_hour = self._hour_start(0)
            for d in range(1, 8):
                self._insert_events(service, current_hour - timedelta(days=d), 10)
            self._insert_events(service, current_hour, 12)  # only 1.2x — not a spike

            anomalies = compute_anomalies(spike_multiplier=3.0)
            assert not any(a["service"] == service for a in anomalies)

    def test_ignores_low_volume_noise(self, app):
        with app.app_context():
            from utils.usage_tracker import compute_anomalies
            service = "email_imap"
            current_hour = self._hour_start(0)
            self._insert_events(service, current_hour, 2)  # below _MIN_EVENTS_FOR_SIGNAL

            anomalies = compute_anomalies(spike_multiplier=1.5)
            assert not any(a["service"] == service for a in anomalies)


# ── Hourly rollup persistence (Redis -> durable table) ──────────────────────────

class TestHourlyRollupPersistence:
    def test_persists_redis_counters_into_durable_table(self, app):
        import tasks.usage_tasks as usage_tasks
        import tasks._app_singleton as app_singleton
        app_singleton._app = app  # reuse the test app/db instead of spinning up a new one (shared singleton — see tasks/_app_singleton.py)

        hour_start = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(
            minute=0, second=0, microsecond=0
        )

        mock_redis = MagicMock()
        mock_redis.hgetall.return_value = {
            "devices|GET|count": "42",
            "devices|GET|errors": "2",
            "devices|GET|latency_sum": "4200",
        }

        with patch("utils.cache._get_client", return_value=mock_redis):
            result = usage_tasks.persist_hourly_usage_rollup()

        assert result["rows"] == 1
        with app.app_context():
            from models.usage import ApiUsageHourly
            row = ApiUsageHourly.query.filter_by(
                bucket_start=hour_start, endpoint="devices", method="GET"
            ).first()
            assert row is not None
            assert row.request_count == 42
            assert row.error_count == 2
            assert row.total_latency_ms == 4200


# ── Retention pruning ────────────────────────────────────────────────────────────

class TestUsageRetentionPruning:
    def test_prune_old_data_deletes_expired_usage_rows(self, app):
        import tasks.maintenance_tasks as maintenance_tasks
        import tasks._app_singleton as app_singleton
        app_singleton._app = app  # shared singleton — see tasks/_app_singleton.py

        with app.app_context():
            from extensions import db
            from models.usage import ApiUsageEvent, ApiUsageHourly

            old_event = ApiUsageEvent(
                service="ai_assistant", status="success",
                created_at=datetime.now(timezone.utc) - timedelta(days=91),
            )
            recent_event = ApiUsageEvent(
                service="ai_assistant", status="success",
                created_at=datetime.now(timezone.utc) - timedelta(days=1),
            )
            old_hourly = ApiUsageHourly(
                bucket_start=datetime.now(timezone.utc) - timedelta(days=181),
                endpoint="old_endpoint", method="GET", request_count=1,
            )
            db.session.add_all([old_event, recent_event, old_hourly])
            db.session.commit()

            recent_event_id = recent_event.id

        result = maintenance_tasks.prune_old_data()

        assert result["usage_events_deleted"] >= 1
        assert result["usage_hourly_deleted"] >= 1
        with app.app_context():
            from extensions import db
            from models.usage import ApiUsageEvent
            assert db.session.get(ApiUsageEvent, recent_event_id) is not None
