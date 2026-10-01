# RMM System

A NinjaOne-style Remote Monitoring & Management platform built in-house. Monitor devices, manage patches, run scripts, respond to alerts, and handle client billing — all from a single dashboard.

**Stack:** Flask API · Streamlit Dashboard · React Frontend (optional) · Python Agent · PostgreSQL · Redis/Celery

---

## Features

| Category | What's included |
|----------|----------------|
| **Monitoring** | Real-time CPU/RAM/disk metrics, device health map, 7-day history fallback, auto-refresh via `st.fragment` |
| **Alerts** | Rule-based alerting (threshold + offline), auto-resolve on recovery, SMTP + Slack + Teams + custom webhook |
| **Devices** | Agent-managed (Windows/macOS/Linux) + agentless WiFi devices (iOS/Android/IoT) + screenshot capture |
| **Mobile Device Management** | Real Android management (lock/wipe/lost-mode/compliance) via Google's Android Management API — no custom agent on the phone, consent-gated BYOD + corporate enrollment via QR code |
| **Tickets** | Full helpdesk ticketing with comments, priority, assignee, SLA due dates, status workflow |
| **SLA Policies** | Configurable SLA resolution targets per priority, per-customer overrides, auto due-date calc |
| **Patch Management** | OS patches via WUA (Windows), softwareupdate/brew (macOS), apt/dnf/yum/pacman (Linux), winget |
| **Scripts** | Run PowerShell/bat/Python/shell scripts remotely, 7 built-in maintenance scripts |
| **Automation** | Scheduled automation profiles (weekly maintenance, patching, cleanup) |
| **Network Discovery** | ICMP sweep + OUI/port/rDNS platform detection, saves agentless device records |
| **Reports** | CSV reports: device health, patch compliance, alert summary, software inventory |
| **Billing** | Invoice creation, recurring auto-invoices by device count, per-customer billing profiles |
| **Auth & Security** | JWT + refresh tokens, TOTP MFA, role-based access control (5 roles), superadmin, Sentry error tracking |
| **AI Assistant** | Context-aware chat widget on every page, JWT role-scoped, rate-limited, hallucination guardrails |
| **IoT / MQTT** | IoT sensor agent for Raspberry Pi, MQTT ingestion, SNMP polling, sensor dashboard page |
| **React Frontend** | Full TypeScript/React/Vite frontend — equivalent to all Streamlit pages, served from `frontend/` |
| **GDPR** | Data export (Art. 20) + erasure/anonymisation (Art. 17) endpoints for admin use |
| **Database Backup** | Nightly pg_dump via Celery beat, gzip compressed, configurable retention |
| **API Docs** | Interactive Swagger/OpenAPI 3.0 UI at `/api/docs`, raw spec at `/api/openapi.json` |
| **Admin** | Audit log, user management, org enrollment token, server IP display, GDPR controls |
| **Usage Monitoring** | Superadmin-only API/AI-token usage tracking — per-service call counts, token consumption, estimated cost, error rates, trend charts, spike detection with real email/webhook alerts |

---

## Architecture

```
Browser → Streamlit Dashboard (:8501)   OR   React Frontend (:3000)
               │ REST/JWT                              │ REST/JWT
               └──────────────┬────────────────────────┘
                              ▼
                         Flask API (:5000)
                         ├── PostgreSQL (:5432)  — all persistent data
                         ├── Redis (:6379)       — Celery broker/backend + response cache
                         └── Celery Worker + Beat — background tasks

Agent (on each managed Windows/macOS/Linux machine)
  └── heartbeat every 60s → POST /api/agents/<id>/heartbeat
  └── polls tasks → GET /api/agents/<id>/tasks
  └── screenshot every 5 min → POST /api/agents/<id>/screenshot

IoT Sensor Agent (Raspberry Pi / Linux SBC)
  └── sensor readings → POST /api/sensors/<device_id>/readings
  └── (optional) MQTT broker → Celery MQTT task → same endpoint

Managed Android phones (no RMM agent installed)
  └── owner scans enrollment QR → Google provisions its own
      "Android Device Policy" app → phone checks in with Google directly
  └── Flask API ↔ Android Management API (Google) — policy push, commands,
      device list — via api/utils/android_mgmt.py
  └── tasks.mdm_tasks.sync_all_mdm_integrations (5-min beat) reconciles
      Google's device state into local Device/MobileEnrollment rows
```

---

## Quick Start (Docker — recommended)

**Prerequisites:** Docker Desktop

```bash
# 1. Clone
git clone https://github.com/rigwe1965/remotemanagementsystem.git
cd remotemanagementsystem

# 2. Create API env file
cp .env.example api/.env
# Edit api/.env — set SECRET_KEY, JWT_SECRET_KEY, ORG_REGISTRATION_TOKEN, SUPERADMIN_PASSWORD

# 3. Start everything
docker-compose up -d

# 4. Open dashboard
# http://localhost:8501
# Health check: http://localhost:5000/api/health
```

> **Note:** Use `@db:5432` (not `@localhost:5432`) in `DATABASE_URL` when running with Docker.

---

## Manual Setup (Development)

### Prerequisites

- Python 3.11+
- PostgreSQL 14+
- Redis (or [Memurai](https://www.memurai.com/) on Windows)

### 1 — Database

```sql
CREATE USER rmm_app WITH PASSWORD 'your_password';
CREATE DATABASE rmmdb OWNER rmm_app;
GRANT ALL PRIVILEGES ON DATABASE rmmdb TO rmm_app;
```

### 2 — API

```powershell
cd api
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy ..\\.env.example .env   # then edit .env
flask --app app:create_app db upgrade
python app.py
```

### 3 — Celery Worker + Beat (separate terminals)

```powershell
cd api
.\venv\Scripts\Activate.ps1
celery -A tasks.celery_app worker --pool=solo -l info   # Terminal 2
celery -A tasks.celery_app beat -l info                 # Terminal 3
```

### 4 — Dashboard (Streamlit)

```powershell
cd dashboard
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

### 4b — React Frontend (optional alternative UI)

```powershell
cd frontend
npm install
npm run dev    # dev server at http://localhost:3000
# Production build:
npm run build  # output in frontend/dist/
```

Set `CORS_ORIGINS=http://localhost:3000` in `api/.env` when using the React frontend.

### 5 — Agent (on each managed machine)

```powershell
cd agent
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python setup_agent.py <server_ip> <org_token>   # patches config.ini automatically
python rmm_agent.py
```

The org token is shown in **Admin → System Info → Agent Enrollment Token**.

**PyInstaller binary (no-Python deployment):**

```powershell
cd agent
pip install pyinstaller
python build.py
# Output: agent/dist/rmm_agent.exe (Windows) or agent/dist/rmm_agent (Linux/macOS)
# Copy dist/rmm_agent* + dist/config.ini to target machine and run directly
```

**IoT Sensor Agent (Raspberry Pi / Linux SBC):**

```bash
cd agent
pip install -r requirements.txt
python setup_agent.py <server_ip> <org_token>
python iot_agent.py
```

Reads from hwmon (CPU temp), DHT11/DHT22, BME680, PIR motion, door reed switch. All sensor libraries are optional — missing ones are silently skipped.

---

## Environment Variables

Copy `.env.example` to `api/.env` and fill in:

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | ✓ | Flask secret — min 32 chars |
| `JWT_SECRET_KEY` | ✓ | JWT signing key — min 32 chars |
| `DATABASE_URL` | ✓ | PostgreSQL connection string |
| `ORG_REGISTRATION_TOKEN` | ✓ | Shared secret for agent registration |
| `SUPERADMIN_PASSWORD` | ✓ | Superadmin password — min 10 chars |
| `REDIS_URL` | — | Default: `redis://localhost:6379/0` |
| `CORS_ORIGINS` | — | Default: `http://localhost:8501` |
| `SUPERADMIN_EMAIL` | — | Default: `superadmin@rmm.local` |
| `SMTP_HOST` | — | Omit to disable email alerts |
| `ANTHROPIC_API_KEY` | — | Enables AI Assistant (Claude Haiku 4.5). Omit to disable. |
| `AI_ASSISTANT_MODEL` | — | Default: `claude-haiku-4-5-20251001` |
| `AI_ASSISTANT_ENABLED` | — | Default: `true`. Set `false` to hide widget. |
| `AI_ASSISTANT_COST_PER_1M_INPUT` / `_OUTPUT` | — | $ per 1M tokens, used only to display an estimated cost on the superadmin Usage Monitoring page/report. Defaults: `1.00` / `5.00`. |
| `BACKUP_DIR` | — | Directory for nightly DB backups. Default: `../backups` |
| `BACKUP_RETAIN_DAYS` | — | Days to keep backup files. Default: `7` |
| `SENTRY_DSN` | — | Sentry error tracking DSN. Omit to disable. Free tier: 10K errors/month. |
| `MQTT_HOST` | — | MQTT broker hostname for IoT ingestion. Omit to disable MQTT polling. |
| `MQTT_PORT` | — | Default: `1883` |
| `MQTT_USERNAME` | — | MQTT broker credentials (optional) |
| `MQTT_PASSWORD` | — | MQTT broker credentials (optional) |
| `MQTT_TOPIC_PREFIX` | — | Default: `rmm`. Topic pattern: `{prefix}/{device_id}/sensors/{type}` |
| `SNMP_TIMEOUT` | — | SNMP GET request timeout in seconds. Default: `3` |
| `DASHBOARD_URL` | — | React frontend URL for CORS. Default: `http://localhost:3000` |
| `STRIPE_SECRET_KEY` | — | Stripe secret key for payment processing integration |
| `STRIPE_WEBHOOK_SECRET` | — | Stripe webhook signing secret |

Generate secrets:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

> **Security:** The API refuses to start if `SECRET_KEY`, `JWT_SECRET_KEY`, or `SUPERADMIN_PASSWORD` are missing or too short. `ORG_REGISTRATION_TOKEN` must not be the placeholder value.

---

## Default Login

After first startup the superadmin account is auto-seeded from your `.env`:

| Field | Value |
|-------|-------|
| Email | `SUPERADMIN_EMAIL` (default: `superadmin@rmm.local`) |
| Password | `SUPERADMIN_PASSWORD` (from `.env`) |

---

## Dashboard Pages

| # | Page | Access |
|---|------|--------|
| 01 | Overview — stat cards, health map, alerts feed (auto-refreshes every 30s) | All |
| 02 | Tickets | All |
| 03 | Customers | All |
| 04 | Devices — agent + agentless, metrics history, screenshot viewer | All |
| 05 | Alerts — rules + active alerts | All |
| 06 | App Center — software inventory | All |
| 07 | Network Discovery — ICMP scan, save agentless devices | Admin/Tech |
| 08 | Reports — generate + download CSV | Admin/Tech |
| 09 | Billing — invoices | Admin |
| 10 | Admin — audit log, users, system info | Admin |
| 11 | Automation — scheduled profiles | Admin/Tech |
| 12 | OS Patches — WUA/softwareupdate/apt patch records, approve + deploy | Admin/Tech |
| 13 | Software Patches — winget/brew updates (agent devices only) | Admin/Tech |
| 14 | Disk Management | Admin/Tech |
| 14 | Terminal — interactive remote shell (pending-command indicator) | Admin/Tech |
| 15 | Maintenance — reboot, shutdown, cleanup | Admin/Tech |
| 16 | Scripts — run custom scripts remotely | Admin/Tech |
| 17 | My Profile — password change, MFA setup | All |
| 18 | IoT Sensors — sensor readings, charts, MQTT/SNMP status | Admin/Tech |
| 19 | Mobile Enrollment — Android MDM integration setup, policy push, QR enrollment | Admin/Tech |
| 20 | Client Portal — self-service ticket submission + "Enroll My Phone" (client role only) | Client |
| 21 | Client Tickets — client-facing ticket detail/comments | Client |
| 22 | Usage Monitoring — API/AI token usage, cost estimates, trends, spike alerts | Superadmin only |

---

## Roles

| Role | Access |
|------|--------|
| **viewer** | Read-only — dashboard, devices, alerts, tickets |
| **technician** | Operational — scripts, patches, tickets, maintenance |
| **admin** | Full — users, billing, audit log, system config |
| **client** | Customer-facing — own tickets only, read-only device view |
| **superadmin** | System-level — bypasses all role checks, cannot be deleted via UI. The *only* role with access to Usage Monitoring — not even `admin` can see it |

---

## MFA

TOTP-based two-factor authentication (Google Authenticator, Authy, 1Password, etc.):

1. Log in → **My Profile** → **Enable MFA** → scan QR code → enter 6-digit code
2. On next login: password screen → TOTP screen → dashboard
3. Disable: **My Profile** → enter current password → **Disable MFA**

---

## API Endpoints (summary)

All routes prefixed `/api/`. JWT required unless noted.

- **Auth:** `/auth/login`, `/auth/refresh`, `/auth/me`, `/auth/mfa/*`
- **Agents:** `/agents/register` (org_token), `/agents/<id>/heartbeat` (X-Agent-Token)
- **Devices:** `/devices/`, `/devices/<id>`, `/devices/<id>/metrics`, `/devices/<id>/queue_task`
- **Alerts:** `/alerts/`, `/alerts/rules/`
- **Tickets:** `/tickets/`, `/tickets/<id>/comments`
- **Patches:** `/patches/`, `/patches/policies/`
- **Scripts:** `/scripts/`, `/scripts/<id>/run`
- **Automation:** `/automation/profiles/`
- **Network:** `/network/scan`, `/network/agentless_devices`
- **Mobile MDM:** `/mdm/integrations`, `/mdm/enrollments`, `/mdm/devices/<id>/{lock,wipe,start_lost_mode,...}`
- **Reports:** `/reports/`
- **Billing:** `/billing/invoices/`
- **SLA Policies:** `/sla-policies/`, `/sla-policies/<id>`
- **AI Assistant:** `/assistant/chat`
- **Admin:** `/admin/users`, `/admin/org-token`, `/admin/server_ips`, `/admin/users/<id>/gdpr-export`, `/admin/users/<id>/gdpr-delete`
- **Usage Monitoring (superadmin only):** `/admin/usage/summary`, `/admin/usage/timeseries`, `/admin/usage/by-feature`, `/admin/usage/events`, `/admin/usage/alert-config`
- **API Docs:** `/api/docs` (Swagger UI), `/api/openapi.json` (raw spec)
- **Health:** `/health` — `{"status": "ok", "db": true, "redis": true, "version": "1.0.0"}`

Full reference: see `TECHNICAL_GUIDE.md`.

---

## Project Structure

```
RemoteManagementSystem/
├── api/                    # Flask API
│   ├── app.py              # Application factory (Sentry init, JWT cache, cache pre-warm)
│   ├── config.py           # Environment configs (PgBouncer support)
│   ├── models/             # SQLAlchemy models (incl. SLAPolicy, IoT SensorReading, MdmIntegration/MobileEnrollment)
│   ├── routes/             # Blueprint handlers (incl. assistant, docs, sla_policies, sensors, terminal, mobile_mdm)
│   ├── tasks/              # Celery tasks (alert, patch, network, report, automation, backup, billing, mqtt, snmp, mdm)
│   ├── utils/              # Helpers (superadmin, oui, cache, webhook, jwt_cache, tier_gates, crypto, android_mgmt)
│   ├── migrations/         # Alembic migrations
│   ├── screenshots/        # Latest screenshot per device (gitignored, .gitkeep present)
│   ├── tests/              # pytest suite — 490 tests, 72% coverage, one file per routes/tasks module
│   ├── Dockerfile
│   └── requirements.txt
├── dashboard/              # Streamlit frontend
│   ├── app.py              # Login + routing entrypoint
│   ├── pages/              # 21 pages (incl. 18_IoT_Sensors, 20_Client_Portal)
│   ├── utils/              # api_client, auth, nav, styles, formatters, cached_calls, ai_assistant
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/               # React/Vite/TypeScript frontend (alternative UI)
│   ├── src/
│   │   ├── App.tsx          # Router + auth context
│   │   ├── pages/           # 19 pages — not yet at parity with the 22-page Streamlit dashboard
│   │   │                    #   (missing: App Center, IoT Sensors, Mobile Enrollment, Client Tickets)
│   │   │                    #   each page has a Vitest + RTL test file (39 tests total)
│   │   ├── components/      # Shared UI components
│   │   ├── api/             # Axios API client
│   │   ├── contexts/        # Auth context
│   │   └── hooks/           # Data-fetching hooks (TanStack Query)
│   ├── vite.config.ts
│   └── package.json         # React 19, Vite 8, TanStack Query, Tailwind, lucide-react
├── agent/                  # Python monitoring agent
│   ├── rmm_agent.py        # Main loop (screenshot sync, terminal worker)
│   ├── collector.py        # Cross-platform metrics + software + patch collection
│   ├── heartbeat.py        # API client (incl. send_screenshot)
│   ├── executor.py         # Task execution
│   ├── script_runner.py    # PS1/bat/py/sh runner
│   ├── screenshot.py       # Cross-platform screen capture (Pillow, scrot fallback)
│   ├── iot_agent.py        # IoT sensor agent (hwmon, DHT, BME680, PIR, door switch)
│   ├── terminal_worker.py  # WebSocket terminal worker
│   ├── build.py            # PyInstaller single-file binary builder
│   └── setup_agent.py      # One-command WiFi deployment
├── docker-compose.yml      # 6-service stack
├── .env.example            # Environment template
├── audits/                 # Code duplication, testing, security, design-pattern, error-handling audit reports
├── HANDOVER_GUIDE.md       # Full user + ops guide
└── TECHNICAL_GUIDE.md      # Developer reference
```

---

## Documentation

| Document | Audience |
|----------|----------|
| `HANDOVER_GUIDE.md` / `.pdf` | All staff — installation, usage, MFA, troubleshooting |
| `TECHNICAL_GUIDE.md` | Developers — architecture, API reference, security model, extension guide |
| `audits/*.md` | Developers — point-in-time code duplication, testing, security, design-pattern, and error-handling audits, each with a "Remediation Status" section documenting what was fixed |

---

## Production Checklist

- [ ] Set `FLASK_DEBUG=0`, `FLASK_ENV=production`
- [ ] Use HTTPS (nginx reverse proxy + Let's Encrypt)
- [ ] Set `CORS_ORIGINS` to your dashboard/frontend URL (not `*`)
- [ ] Add Redis password (`requirepass` in Memurai/Redis config)
- [ ] Rotate `ORG_REGISTRATION_TOKEN` after all agents registered
- [ ] Enable MFA for all admin accounts
- [ ] Set up automated PostgreSQL backups
- [ ] Run agent as a low-privilege Windows service account (not SYSTEM)
- [ ] Set `ANTHROPIC_API_KEY` or set `AI_ASSISTANT_ENABLED=false` to disable the widget
- [ ] Set `BACKUP_DIR` to a path outside the project directory (network share or cloud-synced)
- [ ] Verify Celery beat is running so nightly backups and recurring invoices fire
- [ ] Set `SENTRY_DSN` to capture production errors (free tier: 10K errors/month at sentry.io)
- [ ] Configure PgBouncer on port 6432 and point `DATABASE_URL` at it for connection pooling
- [ ] Set `MQTT_HOST` only if you have IoT devices publishing to an MQTT broker

---

## License

Internal use only. Not licensed for redistribution.
