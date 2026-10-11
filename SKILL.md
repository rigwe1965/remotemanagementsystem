# SKILL.md — Recreate the RMM System

NinjaOne-style Remote Monitoring & Management system.
Stack: Flask API + Streamlit dashboard + React frontend + Python agent + PostgreSQL + Redis/Celery.

**The repo is the source of truth for code.** This file holds only what you can't read off the code: bootstrap order, design invariants and pitfalls. Day-to-day rules live in `CLAUDE.md`; feature history in `docs/CHANGELOG.md`, `git log` and `audits/`; the original 1,900-line step-by-step build (with full code listings) is archived at `docs/archive/SKILL-full-recreation-guide.md`.

---

## 1. Prerequisites

| Tool | Notes |
|------|-------|
| Python 3.11+ | `python --version` |
| PostgreSQL 15 | port 5432; then `CREATE USER rmm_app WITH PASSWORD '<pw>'; CREATE DATABASE rmmdb OWNER rmm_app;` (no superuser grant) |
| Memurai (Redis for Windows) | port 6379; verify `redis-cli ping` → `PONG` |
| Node + pnpm/npm | React frontend |

## 2. Bootstrap

```powershell
git clone <repo> ; cd RemoteManagementSystem
copy .env.example .env          # fill in secrets (see below); never commit .env
# one venv each: api, dashboard, agent
cd api ; python -m venv venv ; venv\Scripts\activate ; pip install -r requirements.txt
flask db upgrade ; python seed.py     # seeds default customer + built-in scripts
cd ..\dashboard ; python -m venv venv ; venv\Scripts\activate ; pip install -r requirements.txt
cd ..\frontend ; npm install
cd ..\agent ; copy config.ini.example config.ini
.\rmm.ps1 start                 # see CLAUDE.md for flags and manual fallback
```

Secrets: generate `SECRET_KEY`, `JWT_SECRET_KEY` (`secrets.token_hex(32)`) and `ORG_REGISTRATION_TOKEN` (`token_hex(24)`). Every other variable is documented in `.env.example`. **Changing `SECRET_KEY` breaks decryption of stored credentials and MFA secrets** (Fernet key derives from it).

`seed.py` creates `SEED_ADMIN_EMAIL` (default `admin@rmm.local`) with `SEED_ADMIN_PASSWORD`, or a random 16-char password if unset (read it from the seed output). The permanent `superadmin` is created at startup from `SUPERADMIN_EMAIL`/`SUPERADMIN_PASSWORD`. Override both before any non-local use; emergency reset: `cd api ; python reset_superadmin.py <new_password>`.

## 3. Layout

```
api/         Flask app. app.py (create_app), config.py, extensions.py, seed.py
  models/    SQLAlchemy models        routes/    one blueprint per area, registered in app.py
  services/  logic shared by >1 caller (route + AI tool + Celery)
  tasks/     Celery tasks; celery_app.py holds include=[...] and beat_schedule
  utils/     auth_decorators, scope, crypto, pagination, cache, rate_limit, usage_tracker,
             webhook, notifications, builtin_scripts, oui, mdm_client/android_mgmt, psa/
  migrations/ Alembic              reports/ + backups/  runtime output (gitignored)
dashboard/   Streamlit: app.py, pages/NN_Name.py, utils/{api_client,cached_calls,auth,nav,ai_assistant,...}
frontend/    React (Vite, Vitest, Playwright)
agent/       rmm_agent.py (Windows), iot_agent.py (Linux SBC), collector, heartbeat, executor,
             script_runner, setup_agent.py, build.py (PyInstaller)
scripts_library/  seed scripts      docs/  CHANGELOG + archive      audits/  dated audit reports
```

## 4. Design invariants (the non-obvious parts)

**Data model**
- `DeviceMetrics` timestamp field is `collected_at` (not `recorded_at`). Naive datetimes from SQLite/PG must be treated as UTC before comparing.
- `ScriptRun.script_id` is NOT NULL: every device task, including maintenance and patch deploys, points to a `Script` row. Built-ins are `Script(is_builtin=True)` rows upserted at startup by `utils/builtin_scripts.py::ensure_builtin_scripts()`, found by a tag stored in `description`. Valid `task_type`s: `clean_temp, defrag, check_disk, restore_point, clear_browser, reboot, shutdown`.
- Patch deploy builds a transient script (tag `__deploy_patches_transient__`), creates a `ScriptRun`, marks patches `deployed`. `sync_patch_status` (beat, 30 min) auto-approves per `PatchPolicy`.
- `Report.to_dict()` must expose `file_path` (dashboard reads the CSV straight from disk; API and dashboard share a host).
- `Alert.device_id` is NOT NULL, so system-level alerts (e.g. usage anomalies) call `send_alert_notification` / `dispatch_alert_webhooks` directly rather than creating an `Alert`.
- `Device.mdm_enrollment` is a relationship; managed phones keep `is_agentless=True`. Gate MDM actions on `mdm_enrollment.status == "enrolled"`, checked **before** the `is_agentless` branch in the UI. Consent fields on `MobileEnrollment` are real columns because they are the legal record.
- `User.must_change_password` forces a password change before any dashboard navigation (`POST /api/auth/me/force-change-password` clears it).

**Auth and tenancy**
- JWT role lives in `additional_claims`: read it with `get_jwt().get("role")`, never from `get_jwt_identity()`.
- Use the shared helpers (see CLAUDE.md): `require_role`, `require_customer_scope`, `encrypt_cred`/`decrypt_cred`, `paginated_response`. Superadmin bypasses `require_role`, except `routes/usage.py`, which is explicitly superadmin-only with no admin bypass.
- Agent registration takes an optional `customer_id` (validated, active customers only); otherwise it falls back to the first active customer. Agent tokens are stored hashed server-side and DPAPI-encrypted on Windows agents (`DPAPI:` prefix; plaintext legacy values migrate on next save).
- Role-restricted AI pages are enforced server-side via `ai_prompt.py::_PAGE_ALLOWED_ROLES` before Claude is called. Tool execution bypasses Flask-Limiter, so per-tool limits use `utils/rate_limit.py::check_and_increment` (fails open if Redis is down). Mutating AI tools are only staged (`AiPendingAction`); confirm re-derives context from the current JWT.

**Agent**
- Heartbeat loop: non-blocking CPU sample (prime once at startup, then `interval=None`); bounded process scan (3 s, 200-process cap); bounded registry enumeration (20 s); exponential backoff 15 s → 300 s; HTTP 401 triggers re-registration; task results queue locally in `pending_results.json` (cap 100) and flush each cycle.
- Patch scan uses the Windows Update Agent COM API via PowerShell; run the agent as Administrator for patching. `winget list` output contains Unicode progress-bar lines; the parser skips any line with `ord(c) > 127` and parses only after the dashed separator line.
- Always pass `CREATE_NO_WINDOW` to subprocesses; read/write files as UTF-8.

**Agentless / network discovery** (`tasks/network_tasks.py`)
- Identification order: OUI vendor → reverse-DNS hostname → port probe (62078 iOS, 5555 Android, ≥2 of 445/3389/139 Windows, 548 macOS, 22 Linux; skipped for routers) → hostname keyword fallback. Devices with randomized MACs and closed ports stay `unknown`; the manual Edit form is the intended escape hatch.
- `_upsert_agentless_host` matches by MAC, then IP, then bare hostname, and never overwrites an agent-managed device.
- Streamlit renders all tabs at once, so any widget inside a per-tab row renderer needs a `tab_key` in its widget key or you get duplicate-key errors.

**Celery / scheduling**
- Windows needs `--pool=solo`. Register new task modules in `celery_app.py` `include=[...]` and add beat entries there. Duplicate beats are tolerated only because of Redis `SET NX` locks (see CLAUDE.md).
- Beat cadence: alert evaluation 60 s, offline marking 180 s, agentless ping and MDM sync 300 s, patch sync 1800 s, usage rollup and anomaly check hourly, backup and recurring invoices daily.

**Optional integrations** (all no-op silently when unconfigured): SMTP alerts, Slack/Teams/generic webhooks via `AlertRule.notification_channels`, Stripe, ConnectWise/Autotask PSA, Android Management API (credentials uploaded through the UI and stored encrypted, never in `.env`; the bind callback needs a public HTTPS URL), Anthropic AI assistant (`ANTHROPIC_API_KEY`, `AI_ASSISTANT_ENABLED=false` disables it). iOS MDM is a placeholder pending an Apple Business Manager / Fleet / MicroMDM decision.

**Usage monitoring** (superadmin only): `utils/usage_tracker.py::record_event` fails open and logs truncated error text only (never raw response bodies or secrets); per-request counts go to a Redis hash and are rolled up hourly rather than written per request; `compute_anomalies` is the single implementation behind both the summary endpoint and the beat task; its alert config lives in its own table so it never appears on the Alerts page.

## 5. Pitfalls that already cost real bugs

1. `st.cache_data` drops `_`-prefixed params from the cache key. A token param named `_token` leaked one user's data to another. Never underscore a param that scopes the result.
2. Any value rendered with `unsafe_allow_html=True` must go through `esc()`. One missed field is stored XSS.
3. Crypto helpers must fail closed: no `except Exception: return value`.
4. When migrating hand-rolled pagination to `paginated_response`, check the response key first (`items` vs `users`, etc.); one endpoint broke its consumer this way.
5. Single-use tokens: compare the token's `iat` against an existing "last invalidated" timestamp such as `password_changed_at`; beware naive-vs-aware datetime comparison.
6. Tests that run a task against the test DB must set `tasks._app_singleton._app = app`; Streamlit page tests need `streamlit.page_link` and `streamlit.switch_page` patched.
7. A test failure that "shouldn't happen" is often a production bug. Investigate the code before adjusting the assertion.

## 6. Verify

```powershell
.\rmm.ps1 status
curl http://localhost:5000/api/health        # {"status":"ok"}
curl -s -o NUL -w "%{http_code}" http://localhost:8501   # 200
redis-cli ping ; psql -U rmm_app -d rmmdb -c "SELECT 1"
cd api ; python -m pytest tests -q           # plus dashboard, frontend, agent suites
```

## 7. Production security checklist

- [ ] `.env` untracked; `SECRET_KEY`/`JWT_SECRET_KEY` random 32-byte hex
- [ ] Superadmin and seeded admin passwords set/changed; `ORG_REGISTRATION_TOKEN` rotated once agents are enrolled
- [ ] `FLASK_DEBUG` off; `CORS_ORIGINS` set to your real dashboard/frontend origins (localhost vs 127.0.0.1 must match exactly)
- [ ] `rmm_app` DB user is not a superuser
- [ ] Login rate-limited; JWT lifetimes short (access 900 s, refresh 7 d)
- [ ] `api/reports/` and `backups/` not exposed over HTTP
- [ ] SMTP uses an app-specific password
- [ ] `pip-audit` / `npm audit` clean, or each ignore documented with its reason
