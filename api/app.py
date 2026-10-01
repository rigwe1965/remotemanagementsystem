import os
import time
import uuid
from flask import Flask, request, g
from dotenv import load_dotenv

from config import config_map
from extensions import db, migrate, jwt, cors, limiter, compress

load_dotenv()

# Sentry error tracking — no-op when SENTRY_DSN is unset
_sentry_dsn = os.getenv("SENTRY_DSN", "")
if _sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration
    from sentry_sdk.integrations.celery import CeleryIntegration
    sentry_sdk.init(
        dsn=_sentry_dsn,
        integrations=[FlaskIntegration(), CeleryIntegration()],
        traces_sample_rate=0.05,
        send_default_pii=False,
    )


def _validate_env():
    """Abort startup if critical env vars are missing or insecure."""
    errors = []
    secret_key = os.getenv("SECRET_KEY", "")
    jwt_key = os.getenv("JWT_SECRET_KEY", "")
    sa_password = os.getenv("SUPERADMIN_PASSWORD", "")
    org_token = os.getenv("ORG_REGISTRATION_TOKEN", "")

    if len(secret_key) < 32:
        errors.append("SECRET_KEY must be at least 32 characters")
    if len(jwt_key) < 32:
        errors.append("JWT_SECRET_KEY must be at least 32 characters")
    if not sa_password:
        errors.append("SUPERADMIN_PASSWORD must be set")
    if len(sa_password) < 10:
        errors.append("SUPERADMIN_PASSWORD must be at least 10 characters")
    if not org_token or org_token in ("change-this-to-a-secure-random-token", ""):
        errors.append("ORG_REGISTRATION_TOKEN must be set to a unique random value")

    if errors:
        raise RuntimeError("Environment configuration errors:\n  - " + "\n  - ".join(errors))


def create_app(config_name=None):
    _validate_env()

    if config_name is None:
        config_name = os.getenv("FLASK_ENV", "development")

    app = Flask(__name__)
    app.config.from_object(config_map.get(config_name, config_map["default"]))

    # Extensions
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)

    allowed_origins = os.getenv("CORS_ORIGINS", "http://localhost:8501").split(",")
    cors.init_app(app, resources={r"/api/*": {"origins": [o.strip() for o in allowed_origins]}})
    limiter.init_app(app)
    compress.init_app(app)

    from utils.jwt_cache import install as _install_jwt_cache
    _install_jwt_cache()

    # Without these, flask_jwt_extended's default error bodies use {"msg": ...} —
    # the only place in this whole API that doesn't use this app's {"error": ...}
    # convention (every hand-written error response, and every @app.errorhandler
    # below, uses "error"). A missing/expired/invalid token is the single most
    # common failure a client will see, so keep its shape consistent with everything else.
    @jwt.unauthorized_loader
    def _jwt_missing(reason):
        return {"error": "Authorization token required"}, 401

    @jwt.invalid_token_loader
    def _jwt_invalid(reason):
        # 422, not 401 — flask_jwt_extended's own default status code for this
        # callback (it also covers WrongTokenError, e.g. an access token used
        # where a refresh token is required). Only the body's key changes here.
        return {"error": str(reason) or "Invalid or malformed token"}, 422

    @jwt.expired_token_loader
    def _jwt_expired(jwt_header, jwt_payload):
        return {"error": "Token has expired"}, 401

    @jwt.revoked_token_loader
    def _jwt_revoked(jwt_header, jwt_payload):
        return {"error": "Token has been revoked"}, 401

    # Warn when running in insecure development mode
    if config_name != "production":
        app.logger.warning(
            "Running in '%s' mode — JWT cookies are NOT secure. "
            "Set FLASK_ENV=production for HTTPS deployments.",
            config_name,
        )

    # Import models so Alembic detects them
    with app.app_context():
        from models import user, device, customer, alert, ticket, patch, script, automation, report, billing, audit  # noqa
        from models import org_settings, user_session, department, terminal, sla_policy, psa_integration  # noqa
        from models import mdm_integration, ai_conversation, usage, triage_category  # noqa
        try:
            from utils.builtin_scripts import ensure_builtin_scripts
            ensure_builtin_scripts()
        except Exception:
            app.logger.warning("Could not sync built-in scripts (DB may not be ready yet)")
        try:
            from utils.superadmin import ensure_superadmin
            ensure_superadmin()
        except Exception:
            app.logger.warning("Could not ensure superadmin (DB may not be ready yet)")
        try:
            from models.org_settings import ensure_org_settings
            ensure_org_settings()
        except Exception:
            app.logger.warning("Could not ensure org settings (DB may not be ready yet)")
        try:
            from utils.helpdesk_dept import ensure_helpdesk_department
            ensure_helpdesk_department()
        except Exception:
            app.logger.warning("Could not ensure Help Desk department (DB may not be ready yet)")
        try:
            from models.audit import NetworkScan
            from datetime import datetime, timezone, timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
            stale = NetworkScan.query.filter(
                NetworkScan.status == "running",
                NetworkScan.started_at < cutoff,
            ).all()
            for s in stale:
                s.status = "failed"
                s.completed_at = datetime.now(timezone.utc)
                s.discovered_hosts = [{"error": "Scan interrupted (server restarted)"}]
            if stale:
                db.session.commit()
                app.logger.info("Marked %d stale running scan(s) as failed", len(stale))
        except Exception:
            app.logger.warning("Could not clean up stale network scans")

        # Warm connection pool — prevents first-request latency spike
        try:
            from sqlalchemy import text as _text
            for _ in range(min(3, app.config.get("SQLALCHEMY_ENGINE_OPTIONS", {}).get("pool_size", 10))):
                db.session.execute(_text("SELECT 1"))
            db.session.remove()
        except Exception as exc:
            app.logger.warning("Connection pool warm-up failed: %s", exc)

        # Pre-warm dashboard Redis cache so first real user never hits DB cold
        try:
            from utils.cache import cache_get, cache_set
            if not cache_get("rmm:dash:summary:all"):
                from sqlalchemy import func, case, and_
                from models.device import Device as _Dev
                from models.alert import Alert as _Alr
                from models.ticket import Ticket as _Tkt
                from models.customer import Customer as _Cust

                dev = db.session.execute(db.select(
                    func.count().label("total"),
                    func.sum(case((_Dev.is_online == True, 1), else_=0)).label("online"),
                    func.sum(case((_Dev.status == "critical", 1), else_=0)).label("critical"),
                    func.sum(case((_Dev.status == "warning", 1), else_=0)).label("warning"),
                ).select_from(_Dev)).one()

                alr = db.session.execute(db.select(
                    func.sum(case((_Alr.status == "open", 1), else_=0)).label("open"),
                    func.sum(case((and_(_Alr.status == "open", _Alr.severity == "critical"), 1), else_=0)).label("critical"),
                ).select_from(_Alr)).one()

                _active = _Tkt.status.in_(["open", "in_progress"])
                tkt = db.session.execute(db.select(
                    func.sum(case((_active, 1), else_=0)).label("open"),
                    func.sum(case((and_(_active, _Tkt.priority == "critical"), 1), else_=0)).label("critical"),
                    func.sum(case((and_(_active, _Tkt.assignee_id == None), 1), else_=0)).label("unassigned"),  # noqa: E711
                    func.sum(case((and_(_active, _Tkt.sla_breached == True), 1), else_=0)).label("sla_breached"),  # noqa: E712
                ).select_from(_Tkt)).one()

                total_customers = db.session.execute(
                    db.select(func.count()).select_from(_Cust).where(_Cust.is_active == True)  # noqa: E712
                ).scalar()

                total = dev.total or 0
                online = dev.online or 0
                cache_set("rmm:dash:summary:all", {
                    "devices": {"total": total, "online": online, "offline": total - online,
                                "critical": dev.critical or 0, "warning": dev.warning or 0},
                    "alerts": {"open": alr.open or 0, "critical": alr.critical or 0},
                    "tickets": {"open": tkt.open or 0, "critical": tkt.critical or 0,
                                "unassigned": tkt.unassigned or 0, "sla_breached": tkt.sla_breached or 0},
                    "customers": {"total": total_customers or 0},
                }, 60)
                db.session.remove()
                app.logger.info("Dashboard cache pre-warmed at startup")
        except Exception as _e:
            app.logger.warning("Cache pre-warm failed: %s", _e)

    # Register blueprints
    from routes.auth import auth_bp
    from routes.agents import agents_bp
    from routes.customers import customers_bp
    from routes.devices import devices_bp
    from routes.alerts import alerts_bp
    from routes.tickets import tickets_bp
    from routes.patches import patches_bp
    from routes.scripts import scripts_bp
    from routes.automation import automation_bp
    from routes.reports import reports_bp
    from routes.billing import billing_bp
    from routes.network import network_bp
    from routes.dashboard import dashboard_bp
    from routes.admin import admin_bp
    from routes.org_settings import org_settings_bp
    from routes.terminal import terminal_bp
    from routes.events import events_bp
    from routes.update import update_bp
    from routes.assistant import assistant_bp
    from routes.docs import docs_bp
    from routes.sla_policies import sla_bp
    from routes.sensors import sensors_bp
    from routes.psa import psa_bp
    from routes.mobile_mdm import mobile_mdm_bp
    from routes.usage import usage_bp
    from routes.ticket_triage import ticket_triage_bp, _triage_categories_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(agents_bp, url_prefix="/api/agents")
    app.register_blueprint(customers_bp, url_prefix="/api/customers")
    app.register_blueprint(devices_bp, url_prefix="/api/devices")
    app.register_blueprint(alerts_bp, url_prefix="/api")
    app.register_blueprint(tickets_bp, url_prefix="/api/tickets")
    app.register_blueprint(patches_bp, url_prefix="/api/patches")
    app.register_blueprint(scripts_bp, url_prefix="/api/scripts")
    app.register_blueprint(automation_bp, url_prefix="/api/automation")
    app.register_blueprint(reports_bp, url_prefix="/api/reports")
    app.register_blueprint(billing_bp, url_prefix="/api/billing")
    app.register_blueprint(network_bp, url_prefix="/api/network")
    app.register_blueprint(dashboard_bp, url_prefix="/api/dashboard")
    app.register_blueprint(admin_bp, url_prefix="/api/admin")
    app.register_blueprint(org_settings_bp, url_prefix="/api/admin")
    app.register_blueprint(terminal_bp, url_prefix="/api/terminal")
    app.register_blueprint(events_bp, url_prefix="/api/events")
    app.register_blueprint(update_bp, url_prefix="/api/agents/update")
    app.register_blueprint(assistant_bp, url_prefix="/api/assistant")
    app.register_blueprint(docs_bp)
    app.register_blueprint(sla_bp, url_prefix="/api/sla-policies")
    app.register_blueprint(sensors_bp, url_prefix="/api/sensors")
    app.register_blueprint(psa_bp, url_prefix="/api/psa")
    app.register_blueprint(mobile_mdm_bp, url_prefix="/api/mdm")
    app.register_blueprint(usage_bp, url_prefix="/api/admin/usage")
    app.register_blueprint(ticket_triage_bp, url_prefix="/api/tickets")
    app.register_blueprint(_triage_categories_bp, url_prefix="/api/triage/categories")

    import redis as redis_lib
    _redis_client = redis_lib.from_url(
        app.config.get("REDIS_URL", "redis://localhost:6379/0"),
        socket_timeout=1,
        socket_connect_timeout=1,
    )

    @app.route("/api/health")
    def health():
        from sqlalchemy import text
        checks: dict = {"version": "1.0.0", "db": False, "redis": False}
        try:
            db.session.execute(text("SELECT 1"))
            checks["db"] = True
        except Exception:
            pass
        try:
            _redis_client.ping()
            checks["redis"] = True
        except Exception:
            pass
        checks["status"] = "ok" if checks["db"] and checks["redis"] else "degraded"
        from flask import jsonify as _j
        return _j(checks), (200 if checks["status"] == "ok" else 503)

    # Request timing + correlation ID
    @app.before_request
    def _start_timer():
        g._start_time = time.monotonic()
        g.request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

    @app.after_request
    def _log_request(response):
        duration_ms = (time.monotonic() - getattr(g, "_start_time", time.monotonic())) * 1000
        rid = getattr(g, "request_id", "-")
        app.logger.info(
            "[%s] %s %s %s %.1fms",
            rid, request.method, request.path, response.status_code, duration_ms,
        )
        try:
            from utils.usage_tracker import record_internal_api_call
            record_internal_api_call(request.endpoint, request.method, response.status_code, duration_ms)
        except Exception:
            pass
        response.headers["X-Request-ID"] = rid
        # Dashboard tokens ride in the URL (?tok=/&rtok=) to survive Streamlit
        # page reloads — see TECHNICAL_GUIDE.md Security Model. This stops them
        # leaking via the Referer header on any outbound link; it does not stop
        # them landing in browser history or server access logs.
        response.headers["Referrer-Policy"] = "no-referrer"
        # audits/security_audit.md Finding H1 — standard hardening headers,
        # applied to every response (mostly JSON, where these are inert but
        # harmless). /api/docs is the one HTML page this app serves itself
        # (SwaggerUI, routes/docs.py) and needs a looser CSP allowing the
        # exact CDN + inline script it actually uses — everything else gets
        # the strict default.
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if request.path == "/api/docs":
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; style-src 'self' https://unpkg.com; "
                "script-src 'self' https://unpkg.com 'unsafe-inline'; "
                "img-src 'self' data:; frame-ancestors 'none'"
            )
        else:
            response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
        return response

    _register_error_handlers(app)
    return app


def _register_error_handlers(app):
    from sqlalchemy.exc import IntegrityError, OperationalError
    from flask_limiter.errors import RateLimitExceeded

    @app.errorhandler(RateLimitExceeded)
    def rate_limit_exceeded(e):
        return {"error": "Too many requests. Please slow down."}, 429

    @app.errorhandler(429)
    def too_many_requests(e):
        return {"error": "Too many requests. Please slow down."}, 429

    @app.errorhandler(400)
    def bad_request(e):
        app.logger.warning("Bad request: %s", e)
        return {"error": "Bad request"}, 400

    @app.errorhandler(404)
    def not_found(e):
        return {"error": "Resource not found"}, 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return {"error": "Method not allowed"}, 405

    @app.errorhandler(422)
    def unprocessable(e):
        app.logger.warning("Validation error: %s", e)
        return {"error": "Validation error"}, 422

    @app.errorhandler(IntegrityError)
    def db_integrity(e):
        db.session.rollback()
        # Log only the exception type — not e.orig which contains DB schema details
        app.logger.warning("IntegrityError: %s", type(e.orig).__name__)
        return {"error": "Conflict: duplicate or constraint violation"}, 409

    @app.errorhandler(OperationalError)
    def db_operational(e):
        db.session.rollback()
        app.logger.error("DB OperationalError: %s", type(e).__name__)
        return {"error": "Database unavailable"}, 503

    @app.errorhandler(Exception)
    def unhandled(e):
        # exc_info=True logs the traceback server-side for ops; client gets no details
        app.logger.error("Unhandled %s: %s", type(e).__name__, str(e)[:200], exc_info=True)
        return {"error": "Internal server error"}, 500


def _refuse_debug_in_production(flask_debug: str, flask_env: str) -> None:
    """Raises RuntimeError if FLASK_DEBUG=1 is combined with FLASK_ENV=production.
    Werkzeug's debug mode has no PIN gate on viewing tracebacks/source/locals —
    never allow it alongside a config that claims to be production. Extracted
    from the __main__ guard below so it's unit-testable without a subprocess
    (see api/tests/test_app_factory.py) — behavior is unchanged."""
    if flask_debug == "1" and flask_env == "production":
        raise RuntimeError(
            "Refusing to start: FLASK_DEBUG=1 with FLASK_ENV=production. "
            "Unset one of them before starting the API."
        )


if __name__ == "__main__":
    app = create_app()
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    _refuse_debug_in_production(os.getenv("FLASK_DEBUG", "0"), os.getenv("FLASK_ENV", ""))
    if debug:
        # Never bind the interactive debugger to 0.0.0.0 — it has no auth on its own.
        app.run(host="127.0.0.1", port=port, debug=True, use_reloader=False)
    else:
        from waitress import serve
        print(f" * Serving on http://{host}:{port} (waitress)")
        serve(app, host=host, port=port, threads=16)
