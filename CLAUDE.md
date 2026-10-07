# RMM Project — Claude Code Instructions

## Project
NinjaOne-style Remote Monitoring & Management system.
Stack: Flask API + Streamlit dashboard + React frontend + Python agent + PostgreSQL + Redis/Celery.
All build phases are complete. Feature history lives in `docs/CHANGELOG.md`, `git log` and `audits/` — read them on demand, not by default.
Check `.claude/state.md` at session start for current context.

## Critical Rules
- Never commit `.env` — use `.env.example` (full env-var surface).
- All file reads/writes: `encoding='utf-8'`; all paths: `pathlib.Path`.
- Windows subprocesses: `CREATE_NO_WINDOW` flag always.
- Celery on Windows: `--pool=solo`.
- One bug fix at a time, verified before moving on.

## Environment (Windows)
- Use PowerShell-compatible commands; do NOT assume `jq`, `/tmp`, or POSIX paths.
- Python/venv paths break often: verify `python --version` and the venv interpreter before installing deps. If python/pnpm/gh is missing from PATH, print the fix rather than failing silently.
- Services (PostgreSQL, Redis/Memurai) often need elevated install/restart. If one is wedged or missing, stop and give me ONE copy-pasteable elevated PowerShell block instead of retrying.

## Git & Push Policy
- Never run bare `git push` or `gh` commands that can hang on an invisible credential prompt. Check `gh auth status` and `git config user.email` FIRST; if either is unset, stop and tell me what to run.
- Git author identity is already configured — don't re-prompt.
- Use `git push 2>&1` with a timeout and report the exit code explicitly; a stalled push is never success.

## Verification Before Reporting Done
- After any multi-file change, run the full suites and report pass counts (api: `cd api ; python -m pytest tests -q`; also dashboard, frontend, agent). No claiming completion on a partial run.
- When starting services, verify with a real HTTP request (curl the health endpoint) and report the status code.
- For frontend↔backend work, confirm the dev-proxy port and CORS origin (localhost vs 127.0.0.1) match.

## Long-Running Work
Don't poll repeatedly. Start the work, then report once at the end or after one clearly-stated wait. If something takes more than a few minutes (model downloads, large installs), pause and offer a cheaper alternative.

## Audits
Produce the report with file:line citations, fix every finding, run tests, commit as a separate PR. Save to `audits/<type>-audit-YYYY-MM-DD.md`.

## Services & Ports
- Flask API: http://localhost:5000 · Streamlit: http://localhost:8501 · React dev: http://localhost:3000
- PostgreSQL: localhost:5432 (db `rmmdb`, user `rmm_app`) · Redis/Memurai: localhost:6379 · PgBouncer (optional): 6432
- Kill by port: `netstat -ano | findstr :<PORT>` then `taskkill /F /PID <PID>`

## Start Services
Preferred: `.\rmm.ps1 start|stop|restart|status [-Agent] [-Frontend]` (also kills duplicate celery beats).

Manual fallback:
```
cd api ; python app.py
cd api ; celery -A tasks.celery_app worker --pool=solo -l info
cd api ; celery -A tasks.celery_app beat -l info --pidfile=celerybeat.pid
cd dashboard ; streamlit run app.py
cd frontend ; npm run dev
cd agent ; python rmm_agent.py        # admin shell for patch management
cd agent ; python iot_agent.py        # Raspberry Pi / Linux SBC
cd agent ; python build.py            # PyInstaller binary
```
Before starting beat, check none is already running. `--pidfile` does NOT stop a duplicate beat on Windows; correctness is guaranteed by Redis `SET NX` locks in `tasks/network_tasks.py::ping_agentless_devices` and `tasks/alert_tasks.py::evaluate_all_rules`.

## Brand
Primary #407E3C · White #FFFFFF · Accent #5a9e56. Dark sidebar, white text, green accents.

## Conventions & Gotchas (read before touching these areas)
Full descriptions of every util/route/task are in `docs/CHANGELOG.md`.

**Architecture**
- Extract route logic to `api/services/*.py` only when called from more than one place (route + AI tool + Celery task, etc.). Single-route logic stays in the route file. Don't extract speculatively.
- Shared helpers — import, never write a second copy: `utils/auth_decorators.py::require_role(*roles)` (superadmin always bypasses; `admin.py` keeps its own DB-loading `_require_admin()`), `utils/scope.py::require_customer_scope(customer_id)` (all tenant-isolation fixes go here), `utils/crypto.py` `encrypt_cred`/`decrypt_cred`, `utils/pagination.py::paginated_response` (returns `{items,total,page,pages}`; exceptions: `devices.py`, `alerts.py::list_alerts`, `usage.py::events`), `utils/ai_client.py::get_anthropic_client()/get_model()`, `utils/mdm_client.py::MdmClient` (implement for any new MDM vendor).
- `utils/crypto.py` fails closed — never add an `except Exception: return value` fallback. Fernet key is `SHA-256("rmm-cred-encryption:" + SECRET_KEY)`. Also encrypts `User.mfa_secret` (use `set_mfa_secret()`/`get_mfa_secret()`).

**Celery / tests**
- Task files use `from tasks._app_singleton import get_app as _get_app`. Tests that run a task against the test DB must set `tasks._app_singleton._app = app` (there is no per-module `_app`).
- `utils/usage_tracker.py::record_internal_api_call` no-ops when `current_app.testing` — tests share the real dev Redis (`REDIS_URL`). `record_event` writes via `db.session` and needs no guard.
- Ticket triage is scheduled from exactly one place, `services/ticket_service.py::create_ticket_service` — don't add another `.delay()` call site. `TriageCategory` has no `"other"` row by design (always-escalate, handled in code). `apply_triage_decision` never trusts the model's own `is_auto_resolvable`.

**Dashboard (Streamlit)**
- `dashboard/utils/cached_calls.py`: **never prefix the token parameter with `_`** — `st.cache_data` drops underscore params from the cache key (caused a real cross-user data leak). Call `st.cache_data.clear()` after mutations. Use these wrappers instead of calling `client.*` directly on hot pages.
- Any value rendered with `unsafe_allow_html=True` must go through `esc()` (stored XSS fixed in `04_Devices.py`).
- `dashboard/utils/auth.py::require_auth()` re-stamps `?tok=`/`?rtok=` on every page load so F5 restores sessions. `nav.py::render_sidebar()` is the shared sidebar. `api_client.py::RMMClient` handles session reuse, retry, 401 refresh.
- Usage Monitoring page and nav are gated to `role == "superadmin"` in the dashboard/React only; the API (`routes/usage.py`) uses `require_role("admin")` like every other route.

**Agent / devices**
- `agent/config.ini` is gitignored (live `device_id` + DPAPI token) — copy `agent/config.ini.example` for new deployments. `setup_agent.py <server_ip> <org_token>` does WiFi deployment.
- Android MDM actions are gated on `device.mdm_enrollment.status == "enrolled"`, not `is_agentless`. iOS is a placeholder only (`get_client()` raises `NotImplementedError`) pending an Apple Business Manager / Fleet / MicroMDM decision.
- `api/utils/superadmin.py` seeds the permanent `superadmin` at every startup (credentials from `SUPERADMIN_EMAIL`/`SUPERADMIN_PASSWORD`, see `.env.example` — always override in production). `api/reset_superadmin.py <new_password>` is the emergency reset.
- `api/utils/jwt_cache.py` monkey-patches flask_jwt_extended's decode with a 60s TTL cache (installed in `create_app()`); `cache.py` offers `cache_get_raw`/`cache_set_raw` for pre-serialized JSON. Both silently no-op if Redis is down.
- `ai_prompt.py::_PAGE_ALLOWED_ROLES` is server-side AI-assistant page authorization — add restricted pages there, not just in `_PAGE_INFO`. Mutating AI tool calls are staged as `AiPendingAction` and need explicit confirm.
