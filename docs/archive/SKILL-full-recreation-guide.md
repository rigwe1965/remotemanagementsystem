# SKILL.md — Recreate RMM System A-Z

> NinjaOne-style Remote Monitoring & Management system.
> Stack: Flask API + Streamlit dashboard + Python agent + PostgreSQL + Redis/Celery.
> All 9 phases + A/B/C optimization pass + D/E/F/G/H/I post-ship phases complete.

---

## Prerequisites

### 1. Install PostgreSQL 15

Download: https://www.enterprisedb.com/downloads/postgres-postgresql-installer

During install:
- Port: `5432`
- Superuser password: set something — you will need it

After install, open pgAdmin or psql and run:

```sql
CREATE USER rmm_app WITH PASSWORD 'changeme';
CREATE DATABASE rmmdb OWNER rmm_app;
GRANT ALL PRIVILEGES ON DATABASE rmmdb TO rmm_app;
```

### 2. Install Memurai (Redis for Windows)

Download: https://www.memurai.com/get-memurai

Install with defaults. Service auto-starts on port `6379`.

Verify: `redis-cli ping` → should return `PONG`

### 3. Python 3.11+

Download: https://www.python.org/downloads/

Check: `python --version`

---

## Project Layout

```
RemoteManagementSystem/
├── .claude/
│   └── state.md
├── .env
├── .env.example
├── .gitignore
├── CLAUDE.md
├── SKILL.md
├── HANDOVER_GUIDE.md
├── TECHNICAL_GUIDE.md
├── api/
│   ├── app.py
│   ├── config.py
│   ├── extensions.py
│   ├── seed.py
│   ├── requirements.txt
│   ├── reports/              ← CSV output dir (created at runtime)
│   ├── models/               ← 11 SQLAlchemy model files
│   ├── routes/               ← 14 route modules (includes assistant.py)
│   ├── tasks/                ← Celery task modules
│   │   └── network_tasks.py
│   ├── reset_superadmin.py
│   └── utils/
│       ├── builtin_scripts.py
│       ├── notifications.py
│       ├── oui.py
│       └── superadmin.py
├── dashboard/
│   ├── app.py
│   ├── requirements.txt
│   ├── .streamlit/config.toml
│   ├── pages/                ← 16 Streamlit pages
│   └── utils/
│       ├── api_client.py
│       ├── ai_assistant.py   ← sidebar AI chat widget (render_ai_assistant)
│       ├── auth.py
│       ├── nav.py
│       ├── styles.py
│       └── formatters.py
├── agent/
│   ├── rmm_agent.py
│   ├── collector.py
│   ├── executor.py
│   ├── heartbeat.py
│   ├── script_runner.py
│   ├── setup_agent.py
│   ├── config.ini
│   └── requirements.txt
└── scripts_library/
    └── windows/
```

---

## Phase 1 — Bootstrap Project

```bash
mkdir RemoteManagementSystem
cd RemoteManagementSystem
git init
```

Create `.gitignore`:
```
.env
__pycache__/
*.pyc
*/venv/
*.egg-info/
.DS_Store
*.log
*.db
reports/
```

---

## Phase 2 — API Backend

### 2.1 Create venv + install deps

```bash
cd api
python -m venv venv
venv\Scripts\activate
pip install flask flask-sqlalchemy flask-migrate flask-jwt-extended flask-cors flask-limiter celery redis psycopg2-binary bcrypt pyotp marshmallow python-dateutil requests python-dotenv gunicorn
pip freeze > requirements.txt
```

### 2.2 `api/extensions.py`

```python
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

db = SQLAlchemy()
migrate = Migrate()
jwt = JWTManager()
cors = CORS()
limiter = Limiter(key_func=get_remote_address, default_limits=["200 per minute"])
```

### 2.3 `api/config.py`

```python
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / '.env')

class Config:
    SECRET_KEY = os.environ['SECRET_KEY']
    SQLALCHEMY_DATABASE_URI = os.environ['DATABASE_URL']
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 10,
        'max_overflow': 20,
        'pool_recycle': 300,
        'pool_pre_ping': True,
    }
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_SECRET_KEY = os.environ['JWT_SECRET_KEY']
    JWT_ACCESS_TOKEN_EXPIRES = int(os.environ.get('JWT_ACCESS_TOKEN_EXPIRES', 900))
    JWT_REFRESH_TOKEN_EXPIRES = int(os.environ.get('JWT_REFRESH_TOKEN_EXPIRES', 604800))
    JWT_TOKEN_LOCATION = ['headers', 'cookies']
    REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
    CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/1')
    RATELIMIT_DEFAULT = "200 per minute"
    ORG_REGISTRATION_TOKEN = os.environ['ORG_REGISTRATION_TOKEN']
```

### 2.4 `api/app.py` (with Phase 5 built-in script sync)

```python
from flask import Flask
from config import Config
from extensions import db, migrate, jwt, cors, limiter

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    cors.init_app(app, resources={r"/api/*": {"origins": "*"}})
    limiter.init_app(app)

    from routes import auth, agents, customers, devices, alerts
    from routes import tickets, patches, scripts, automation
    from routes import reports, billing, network, dashboard, users

    for bp, prefix in [
        (auth.auth_bp,         '/api/auth'),
        (agents.agents_bp,     '/api/agents'),
        (customers.customers_bp, '/api/customers'),
        (devices.devices_bp,   '/api/devices'),
        (alerts.alerts_bp,     '/api/alerts'),
        (tickets.tickets_bp,   '/api/tickets'),
        (patches.patches_bp,   '/api/patches'),
        (scripts.scripts_bp,   '/api/scripts'),
        (automation.automation_bp, '/api/automation'),
        (reports.reports_bp,   '/api/reports'),
        (billing.billing_bp,   '/api/billing'),
        (network.network_bp,   '/api/network'),
        (dashboard.dashboard_bp, '/api/dashboard'),
        (users.users_bp,       '/api/users'),
    ]:
        app.register_blueprint(bp, url_prefix=prefix)

    from routes.assistant import assistant_bp
    app.register_blueprint(assistant_bp, url_prefix="/api/assistant")

    @app.route('/api/health')
    def health():
        return {'status': 'ok'}

    # Sync built-in scripts on startup (Phase 5)
    with app.app_context():
        try:
            from utils.builtin_scripts import ensure_builtin_scripts
            ensure_builtin_scripts()
        except Exception:
            app.logger.warning("Could not sync built-in scripts (DB may not be ready yet)")

    return app

app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
```

### 2.5 Models (11 files in `api/models/`)

See full model code in TECHNICAL_GUIDE.md. Key notes:

- `DeviceMetrics`: field is `collected_at` (not `recorded_at`)
- `Script`: has `is_builtin = db.Column(db.Boolean, default=False)` flag
- `ScriptRun`: `script_id` is NOT NULL FK — all tasks go through Script records
- `AutomationProfile`: JSON columns `disk_config`, `maintenance_config`, `os_patch_config`, `software_patch_config`
- `Report`: `file_path` exposed in `to_dict()` so dashboard can read CSV for download
- `User`: has `must_change_password = db.Column(db.Boolean, default=False, server_default="false")` — set to `True` when admin creates a user with the "Require password change on first login" checkbox; cleared to `False` by `POST /api/auth/me/force-change-password`

### 2.6 Run Migrations

```bash
cd api
venv\Scripts\activate
flask db init
flask db migrate -m "initial"
flask db upgrade
```

### 2.7 Seed DB

```bash
python seed.py
# Creates: admin@rmm.local / Admin1234! + Default Customer + built-in scripts
```

---

## Phase 3 — Celery Tasks

### `api/tasks/celery_app.py`

```python
from celery import Celery
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent.parent / '.env')

celery_app = Celery(
    'rmm',
    broker=os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
    backend=os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/1'),
    include=[
        'tasks.alert_tasks',
        'tasks.patch_tasks',
        'tasks.automation_tasks',
        'tasks.report_tasks',
        'tasks.network_tasks',
    ]
)

celery_app.conf.beat_schedule = {
    'evaluate-alerts-every-60s': {
        'task': 'tasks.alert_tasks.evaluate_all_rules',
        'schedule': 60.0,
    },
    'mark-offline-devices-every-3m': {
        'task': 'tasks.alert_tasks.mark_offline_devices',
        'schedule': 180.0,
    },
    'sync-patch-status-every-30-min': {
        'task': 'tasks.patch_tasks.sync_patch_status',
        'schedule': 1800.0,
    },
    'ping-agentless-devices-every-5-min': {
        'task': 'tasks.network_tasks.ping_agentless_devices',
        'schedule': 300.0,
    },
}

celery_app.conf.task_acks_late = True
celery_app.conf.worker_pool = 'solo'  # Windows: no fork()
```

### Task modules

| File | Tasks | Schedule |
|------|-------|---------|
| `tasks/alert_tasks.py` | `evaluate_all_rules`, `mark_offline_devices` | 60s / 180s beat |
| `tasks/patch_tasks.py` | `deploy_patches(device_id, patch_ids)`, `sync_patch_status` | on-demand / 1800s beat |
| `tasks/automation_tasks.py` | `enqueue_profile_run(profile_id)` | triggered per profile schedule |
| `tasks/report_tasks.py` | `generate_report(report_id)` | triggered on report creation |
| `tasks/network_tasks.py` | `run_network_scan(scan_id)`, `ping_agentless_devices` | on-demand / 300s beat |

---

## Phase 4 — Agent

### 4.1 `agent/config.ini`

```ini
[api]
base_url = http://localhost:5000
org_token = YOUR_ORG_REGISTRATION_TOKEN

[agent]
interval_seconds = 60
software_sync_hours = 6
patch_interval = 3600
version = 0.1.0
log_level = INFO
```

### 4.2 `agent/collector.py` (key functions)

```python
import psutil, socket, platform, hashlib, uuid

def collect_hardware_info():
    hostname = socket.gethostname()
    mac = ':'.join(['{:02x}'.format((uuid.getnode() >> i) & 0xff)
                    for i in range(0, 48, 8)][::-1])
    return {
        'hostname': hostname,
        'platform': platform.system().lower(),
        'os_name': platform.system(),
        'os_version': platform.version(),
        'cpu_brand': platform.processor(),
        'cpu_cores': psutil.cpu_count(),
        'ram_gb': round(psutil.virtual_memory().total / (1024**3), 2),
        'ip_local': socket.gethostbyname(hostname),
        'mac_address': mac,
        'hardware_id': hashlib.sha256(f"{hostname}{mac}".encode()).hexdigest()
    }

def collect_metrics():
    # Non-blocking CPU sample (Phase C-1): prime at startup, then interval=None
    cpu = psutil.cpu_percent(interval=None)
    ram = psutil.virtual_memory()
    disks = []
    for part in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append({
                'mountpoint': part.mountpoint,
                'device': part.device,
                'total_gb': round(usage.total / (1024**3), 2),
                'used_gb':  round(usage.used  / (1024**3), 2),
                'free_gb':  round(usage.free  / (1024**3), 2),
                'percent':  usage.percent,
            })
        except PermissionError:
            pass
    battery = psutil.sensors_battery()
    # Bounded process scan (Phase C-3): 3s deadline, 200-process cap
    procs = sorted(
        psutil.process_iter(['pid', 'name', 'cpu_percent']),
        key=lambda p: p.info['cpu_percent'] or 0, reverse=True
    )[:5]
    return {
        'cpu_pct': cpu,
        'ram_pct': ram.percent,
        'disk_pct': disks[0]['percent'] if disks else 0,
        'battery_pct': battery.percent if battery else None,
        'uptime_seconds': int(psutil.boot_time()),
        'disks': disks,
        'top_processes': [{'pid': p.info['pid'], 'name': p.info['name'],
                           'cpu': p.info['cpu_percent']} for p in procs]
    }

def get_pending_patches():
    """Query Windows Update Agent for pending patches via WUA COM (Phase 6)."""
    import subprocess, json
    ps = r"""
$session = New-Object -ComObject Microsoft.Update.Session
$searcher = $session.CreateUpdateSearcher()
$result = $searcher.Search("IsInstalled=0 and Type='Software'")
$patches = @()
foreach ($u in $result.Updates) {
    $patches += @{name=$u.Title; kb_id=($u.KBArticleIDs -join ','); patch_type='software'}
}
$patches | ConvertTo-Json -Compress
"""
    try:
        out = subprocess.check_output(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps],
            timeout=60, creationflags=0x08000000  # CREATE_NO_WINDOW
        )
        data = json.loads(out.decode('utf-8', errors='replace').strip() or '[]')
        if isinstance(data, dict):
            data = [data]
        return data[:500]
    except Exception:
        return []
```

### 4.3 `agent/heartbeat.py` (key methods)

```python
import requests, configparser
from pathlib import Path

class APIClient:
    def __init__(self):
        cfg = configparser.ConfigParser()
        cfg.read(Path(__file__).parent / 'config.ini', encoding='utf-8')
        self.base_url = cfg['api']['base_url']
        self.org_token = cfg['api']['org_token']
        self.device_token = None
        self.device_id = None

    def register(self, hw_info):
        resp = requests.post(f'{self.base_url}/api/agents/register',
            json={**hw_info, 'org_token': self.org_token}, timeout=10)
        data = resp.json()
        self.device_token = data['agent_token']
        self.device_id = data['device_id']
        return data

    def send_heartbeat(self, metrics):
        """Returns (data, status_code). Caller checks 401 for re-registration (Phase C-5)."""
        resp = requests.post(
            f'{self.base_url}/api/agents/{self.device_id}/heartbeat',
            json={'metrics': metrics},
            headers={'X-Agent-Token': self.device_token},
            timeout=10
        )
        return resp.json(), resp.status_code

    def get_tasks(self):
        resp = requests.get(
            f'{self.base_url}/api/agents/{self.device_id}/tasks',
            headers={'X-Agent-Token': self.device_token},
            timeout=10
        )
        return resp.json()

    def report_patches(self, patches: list) -> bool:
        """Phase 6: report pending OS patches to API."""
        resp = requests.put(
            f'{self.base_url}/api/agents/{self.device_id}/patches',
            json={'patches': patches},
            headers={'X-Agent-Token': self.device_token},
            timeout=30
        )
        return resp.status_code == 200
```

### 4.4 `agent/rmm_agent.py` (main loop)

```python
import time, logging, json
from pathlib import Path
from collector import collect_hardware_info, collect_metrics, get_pending_patches
from heartbeat import APIClient
from executor import TaskExecutor

STATE_FILE  = Path(__file__).parent / 'agent_state.json'
RESULT_FILE = Path(__file__).parent / 'pending_results.json'  # Phase C-6

def main():
    client   = APIClient()
    executor = TaskExecutor(client)

    # Load or register
    state = json.loads(STATE_FILE.read_text(encoding='utf-8')) if STATE_FILE.exists() else {}
    if 'device_id' not in state:
        hw = collect_hardware_info()
        # Prime CPU counter (Phase C-1)
        import psutil; psutil.cpu_percent(interval=1)
        data = client.register(hw)
        state.update({'device_id': data['device_id'], 'token': data['agent_token']})
        STATE_FILE.write_text(json.dumps(state), encoding='utf-8')
    else:
        client.device_id    = state['device_id']
        client.device_token = state['token']

    backoff      = 15          # Phase C-4 exponential backoff
    last_patch   = 0.0
    patch_interval = 3600      # configurable in config.ini

    while True:
        try:
            metrics = collect_metrics()
            data, status = client.send_heartbeat(metrics)
            if status == 401:
                # Re-register (Phase C-5)
                hw = collect_hardware_info()
                client.register(hw)
                continue
            backoff = 15       # reset on success

            tasks = client.get_tasks()
            for task in tasks.get('tasks', []):
                executor.run(task)

            # Patch scan cycle (Phase 6)
            if time.time() - last_patch > patch_interval:
                patches = get_pending_patches()
                if patches:
                    client.report_patches(patches)
                last_patch = time.time()

        except Exception as e:
            logging.error(f'Loop error: {e}')
            time.sleep(min(backoff, 300))
            backoff = min(backoff * 2, 300)
            continue

        time.sleep(60)

if __name__ == '__main__':
    main()
```

---

## Phase 5 — Built-in Scripts + Maintenance Dispatch

### Why this design

`ScriptRun.script_id` is NOT NULL — all device tasks must point to a `Script` record. Instead of a new DB table, Phase 5 creates 7 PowerShell scripts as `Script` rows with `is_builtin=True` at API startup. Maintenance actions queue `ScriptRun` records against these built-in scripts. The agent picks them up via the existing `get_tasks` poll.

### `api/utils/builtin_scripts.py` (core of Phase 5)

```python
TASK_TYPE_TO_TAG = {
    "clean_temp":    "__builtin_clean_temp__",
    "defrag":        "__builtin_defrag__",
    "check_disk":    "__builtin_check_disk__",
    "restore_point": "__builtin_restore_point__",
    "clear_browser": "__builtin_clear_browser__",
    "reboot":        "__builtin_reboot__",
    "shutdown":      "__builtin_shutdown__",
}

BUILTIN_SCRIPTS = {
    "clean_temp": {
        "name": "Built-in: Clean Temp Files",
        "content": "Remove-Item -Path $env:TEMP\\* -Recurse -Force -ErrorAction SilentlyContinue",
        "file_type": "ps1",
    },
    "defrag": {
        "name": "Built-in: Defragment",
        "content": "Optimize-Volume -DriveLetter C -Defrag -Verbose",
        "file_type": "ps1",
    },
    # check_disk: chkdsk C: /f — schedules for next reboot if drive locked; exits 0 always
    # restore_point, clear_browser, reboot, shutdown: see builtin_scripts.py for full content
}

def ensure_builtin_scripts():
    """Upsert Script records for all built-in task types. Called at app startup."""
    from models.script import Script
    from extensions import db
    for task_type, tag in TASK_TYPE_TO_TAG.items():
        spec = BUILTIN_SCRIPTS[task_type]
        existing = Script.query.filter_by(name=spec["name"]).first()
        if not existing:
            s = Script(name=spec["name"], content=spec["content"],
                       file_type=spec["file_type"], is_builtin=True,
                       description=tag)
            db.session.add(s)
    db.session.commit()

def get_builtin_script_id(task_type: str):
    """Return Script.id for a task_type, or None."""
    from models.script import Script
    tag = TASK_TYPE_TO_TAG.get(task_type)
    if not tag:
        return None
    s = Script.query.filter_by(description=tag, is_builtin=True).first()
    return s.id if s else None
```

### Device task queue endpoint

`POST /api/devices/<device_id>/queue_task`
Body: `{"task_type": "clean_temp", "timeout_seconds": 300}`

Valid `task_type` values: `clean_temp`, `defrag`, `check_disk`, `restore_point`, `clear_browser`, `reboot`, `shutdown`

### Automation profile dispatch (`api/tasks/automation_tasks.py`)

```python
def _dispatch_profile_tasks(profile, device_id, db_session):
    """Create ScriptRun records for all enabled tasks in a profile."""
    from utils.builtin_scripts import get_builtin_script_id
    from models.script import ScriptRun

    disk_cfg  = profile.disk_config or {}
    maint_cfg = profile.maintenance_config or {}

    task_map = {
        'defrag':       disk_cfg.get('defrag'),
        'check_disk':   disk_cfg.get('checkdisk'),
        'clean_temp':   maint_cfg.get('delete_temp'),
        'restore_point': maint_cfg.get('restore_point'),
        'clear_browser': maint_cfg.get('clear_history'),
        'reboot':       maint_cfg.get('reboot'),
        'shutdown':     maint_cfg.get('shutdown'),
    }

    for task_type, enabled in task_map.items():
        if not enabled:
            continue
        script_id = get_builtin_script_id(task_type)
        if script_id:
            db_session.add(ScriptRun(
                script_id=script_id,
                device_id=device_id,
                timeout_seconds=1800 if task_type == 'defrag' else 300,
            ))
```

---

## Phase 6 — Patch Management

### Flow

1. Agent calls `get_pending_patches()` every `patch_interval` seconds (default 3600s)
2. Agent calls `PUT /api/agents/<device_id>/patches` with patch list
3. API deduplicates by patch name, creates `PatchRecord` rows with `status="pending"`
4. Celery beat runs `sync_patch_status()` every 30 min — auto-approves based on `PatchPolicy` flags
5. Dashboard shows patches; technician clicks "Deploy Selected"
6. Dashboard calls `POST /api/devices/<device_id>/deploy_patches` with `patch_ids`
7. Celery `deploy_patches.delay(device_id, patch_ids)` builds a PS1 script, creates a `ScriptRun`, marks patches as "deployed"

### `api/tasks/patch_tasks.py` key logic

```python
@celery_app.task
def deploy_patches(device_id: str, patch_ids: list):
    """Build transient PS1 script from approved patches, create ScriptRun."""
    # Finds PatchRecords by ID, builds Install-WindowsUpdate call
    # Creates/updates Script record with tag __deploy_patches_transient__
    # Creates ScriptRun pointing to that script
    # Marks PatchRecords as status='deployed'

@celery_app.task
def sync_patch_status():
    """Auto-approve patches based on PatchPolicy flags."""
    # Iterates PatchPolicies
    # Checks auto_approve_critical, auto_approve_security, etc.
    # Respects excluded_software list
    # Updates matching PatchRecord.status to 'approved'
```

---

## Phase 7 — Alert Email Notifications

### `api/utils/notifications.py`

```python
import smtplib, os
from email.mime.text import MIMEText

def send_alert_notification(rule_name: str, device_hostname: str,
                             message: str, emails: list):
    """Send email alert. No-ops silently if SMTP_HOST not configured."""
    host = os.environ.get('SMTP_HOST')
    if not host or not emails:
        return
    port = int(os.environ.get('SMTP_PORT', 587))
    user = os.environ.get('SMTP_USER', '')
    pwd  = os.environ.get('SMTP_PASS', '')
    from_addr = os.environ.get('SMTP_FROM', user)

    msg = MIMEText(f"Rule: {rule_name}\nDevice: {device_hostname}\n\n{message}")
    msg['Subject'] = f"[RMM Alert] {rule_name} — {device_hostname}"
    msg['From']    = from_addr
    msg['To']      = ', '.join(emails)

    with smtplib.SMTP(host, port) as smtp:
        if port != 25:
            smtp.starttls()
        if user:
            smtp.login(user, pwd)
        smtp.sendmail(from_addr, emails, msg.as_string())
```

Integration in `alert_tasks.py`:
```python
channels = rule.notification_channels or {}
emails   = channels.get('email', [])
if emails:
    from utils.notifications import send_alert_notification
    send_alert_notification(rule.name, device.hostname, alert.message, emails)
```

Required `.env` vars (all optional — skip to disable email):
```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASS=your_app_password
SMTP_FROM=rmm@yourcompany.com
```

---

## Phase 8 — Ticket Assignment

Ticket model has `assignee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)`.

Dashboard `02_Tickets.py` uses three columns per ticket: Update Status | Assign To | Add Comment.

`PUT /api/tickets/<id>` accepts `{"assignee_id": <user_id>}` — same endpoint as status update.

---

## Phase 9 — Report Generation

### Flow

1. Dashboard `POST /api/reports` creates a `Report` record and returns `report.id`
2. API immediately dispatches `generate_report.delay(report.id)`
3. Celery worker runs `generate_report(report_id)`:
   - Queries DB for the relevant data based on `template_type`
   - Writes CSV to `api/reports/<report_id>_<name>.csv`
   - Updates `report.file_path` in DB
4. Dashboard polls or refreshes — when `file_path` is set, shows download button
5. `st.download_button` reads file bytes directly from disk path

### Templates

| `template_type` | Data collected |
|---|---|
| `device_health` | All devices + latest metrics (batch query) |
| `patch_compliance` | All patch records + device names |
| `alert_summary` | All alerts + rule names + device names |
| `software_inventory` | All installed software + device names |
| `ticket_summary` | All tickets + customer names |

### `Report.to_dict()` must include `file_path`

```python
def to_dict(self):
    return {
        'id': self.id,
        'name': self.name,
        'template_type': self.template_type,
        'format': self.format,
        'file_path': self.file_path,   # ← required for dashboard download
        'has_file': bool(self.file_path),
        'created_at': self.created_at.isoformat() if self.created_at else None,
    }
```

---

## Phase A — API Optimizations

| Item | What was done |
|------|--------------|
| A-1 | Composite DB indexes on 6 high-query tables (Alembic migration) |
| A-2 | Dashboard summary: 8 COUNT queries → 4 aggregations |
| A-3 | Health map `.all()` → `.limit(500)` |
| A-4 | N+1 devices/metrics: batch fetch latest metric per device via subquery |
| A-5 | N+1 agents/tasks: pre-fetch scripts by id dict |
| A-6 | Automation device-loop offloaded to Celery |
| A-7 | DB pool: `pool_size=10`, `max_overflow=20` |
| A-8 | Global Flask error handlers (400/404/409/503/500) |
| A-9 | Request logging middleware (before/after_request with ms timing) |
| A-10 | Celery `acks_late=True`, retry on `OperationalError` |

---

## Phase B — Dashboard Optimizations

| Item | What was done |
|------|--------------|
| B-1 | `requests.Session` reuse via `st.session_state["_rmm_client"]` |
| B-2 | Retry on transient failures: 3 attempts, backoff 0.5/1.0/2.0s |
| B-3 | Token auto-refresh on 401 (POST /api/auth/refresh, retry once) |
| B-4 | Access token persisted in `?tok=` URL param; refresh token in `?rtok=`. Both re-stamped on every authenticated page load by `require_auth()` so F5 restores full session |
| B-5 | `st.cache_data` wrappers (TTL 30–120s by endpoint type) |
| B-6 | `st.spinner` on all data loads across all 16 pages |
| B-7 | Replaced hard `st.stop()` with `st.warning` (graceful degradation) |
| B-8 | Contextual error messages on all pages |

---

## Phase C — Agent Optimizations

| Item | What was done |
|------|--------------|
| C-1 | Non-blocking CPU sample: `interval=None` + startup prime |
| C-2 | Bounded registry enumeration: 20s hard deadline |
| C-3 | Bounded process scan: 3s deadline + 200-process cap |
| C-4 | Exponential backoff on heartbeat failures: 15s → 300s cap |
| C-5 | 401 re-registration flow in main loop |
| C-6 | Local task result queue: `pending_results.json`, cap 100, flush each cycle |
| C-7 | Structured logging with `DeviceFilter` + classified exception types |

---

## Post-Ship Features

### Force Password Change on First Login

**How it works:**
1. Admin creates (or edits) a user in `Admin → Users` and checks **"Require password change on first login"**.
2. API sets `user.must_change_password = True` in the DB.
3. On next login, `dashboard/app.py` reads `st.session_state["user"]["must_change_password"]`.
4. If `True`, `show_force_change_password()` is rendered instead of the normal dashboard — user cannot navigate away.
5. On submission, dashboard calls `client.force_change_password(new_password)` → `POST /api/auth/me/force-change-password`.
6. API sets new bcrypt hash and clears the flag. User is redirected to the normal dashboard.

**Files changed:**
- `api/models/user.py` — `must_change_password` column + exposed in `to_dict()`
- `api/routes/auth.py` — `POST /api/auth/me/force-change-password` endpoint
- `api/routes/admin.py` — `create_user` + `update_user` accept `must_change_password` bool
- `dashboard/utils/api_client.py` — `force_change_password(new_password)` method
- `dashboard/pages/10_Admin.py` — checkbox in create + edit user forms
- `dashboard/app.py` — routing block + `show_force_change_password()` function

**Migration:** `api/migrations/versions/93baa3927b0c_add_must_change_password_to_users.py`

### Superadmin Role

**What it is:** A permanent highest-privilege account auto-seeded at every API startup. Cannot be deleted or modified via the API or dashboard UI.

**Files:**
- `api/utils/superadmin.py` — `ensure_superadmin()`: queries for an existing `superadmin` role user; creates one if absent using `SUPERADMIN_EMAIL`/`SUPERADMIN_PASSWORD` env vars (defaults: `superadmin@rmm.local` / `SuperAdmin@RMM1`). Called from `create_app()` in `api/app.py`.
- `api/reset_superadmin.py` — CLI: `python reset_superadmin.py <new_password>` (min 10 chars). Resets password without a JWT token. Use when locked out of all admin accounts.
- `api/routes/admin.py` — PUT and DELETE endpoints return 403 `"Cannot modify superadmin account"` if target user has role `superadmin`.
- All 9 route files — `_require_role()` helper has superadmin bypass: `if claims.get("role") == "superadmin": return None`
- `dashboard/pages/10_Admin.py` — role guard changed to `role not in ("admin", "superadmin")`; superadmin row in Users tab shows "Protected — use CLI" instead of Edit/Delete buttons; `ROLE_COLORS` includes `"superadmin": "#7C3AED"`.
- `dashboard/utils/nav.py` and `dashboard/app.py` — Admin Panel button shown for `role in ("admin", "superadmin")`; Business section shown for `role in ("admin", "superadmin", "technician")`; role pill includes `"superadmin": ("#7C3AED", "#7C3AED15")`.

**Env vars (optional):**
```
SUPERADMIN_EMAIL=superadmin@rmm.local
SUPERADMIN_PASSWORD=SuperAdmin@RMM1
```

**Emergency recovery:**
```bash
cd api
python reset_superadmin.py <new_password>
```

---

### Agentless Device Identification Enhancements

**Port probing (`api/tasks/network_tasks.py`):**

`_probe_platform(ip)` is called when OUI lookup returns `platform == "unknown"`. It tries 6 TCP ports with a short timeout:

| Port | Platform |
|------|----------|
| 62078 | iOS (iTunes Wi-Fi sync) |
| 5555 | Android (ADB) |
| 445, 3389, 139 | Windows (SMB/RDP/NetBIOS) |
| 548 | macOS (AFP) |
| 22 | Linux (SSH) |
| All closed | `("unknown", "unknown")` |

> **Limitation:** Modern phones randomize MAC addresses per network, which breaks OUI lookup. They also typically close all probed ports. Devices with randomized MACs and no open ports remain "Unknown" — use the manual Edit form.

**Reverse DNS (`api/tasks/network_tasks.py`):**

`_get_hostname(ip)` calls `socket.gethostbyaddr(ip)[0]` for each live host discovered during a scan. The result (e.g. `iPhone.local`) is stored in `discovered_hosts` and passed to `_upsert_agentless_host()` as the `hostname` parameter. On new records, the device hostname is set to `hostname or ip`.

**Manual Edit form (`dashboard/pages/04_Devices.py`):**

Each agentless device row now has an Edit button alongside Ping Now and Delete. Clicking Edit shows an inline `st.form` with:
- `hostname` — text_input
- `platform` — selectbox (unknown, windows, mac, linux, android, ios)
- `device_type` — selectbox (unknown, desktop, laptop, mobile, server)

On submit, calls `client.update_device(device_id, {hostname, platform, device_type})`.

**Duplicate widget key fix (`dashboard/pages/04_Devices.py`):**

Root cause: Streamlit renders all tabs simultaneously. A device appearing in both "All" and a platform-specific tab caused duplicate widget keys (e.g. `gauge_<uuid>` created twice).

Fix: `tab_key` parameter added to `_render_agent_row(device, tab_key="")` and `_render_agentless_row(device, tab_key="")`. All widget keys inside those functions are prefixed with `tab_key`. The render loop passes `tab_key=name` where `name` is the tab label string.

**`delete_device` in `api_client.py`:**

Added `delete_device(device_id)` → `DELETE /api/devices/<id>`. Used by the Delete button on agentless device rows.

---

### Software Patches — Winget Unicode Fix

**Root cause:** `winget list` outputs Unicode block-character progress bars (█▒░, U+2588–U+2593) before the real data table. The old parser was ingesting these as software name/version.

**Fix in `agent/collector.py` `_get_winget_software()`:**
- Skip any line containing characters with `ord(c) > 127`
- Find the separator line (only `-`, `_`, space chars, length > 10)
- Parse only lines after the separator

**Defence-in-depth in `dashboard/pages/13_Software_Patches.py`:**
- `_clean(text)` strips any remaining chars in U+2500–U+259F (block/box-drawing) before HTML render
- All three fields (name, version, publisher) run through `html.escape(_clean(...))`

---

## Phase D — WiFi & Agentless Device Support

### D.1 Database Migration

Migration file: `api/migrations/versions/f3e2d1c0b9a8_agentless_device_columns.py`
Chains after: `93baa3927b0c`

New columns on `devices` table:

```python
is_agentless  = db.Column(db.Boolean,     default=False, nullable=False)
device_type   = db.Column(db.String(50),  default='laptop', nullable=False)
#   Valid values: laptop | desktop | mobile | server | unknown
vendor        = db.Column(db.String(255), nullable=True)
#   OUI lookup result e.g. "Apple, Inc."
# customer_id changed from nullable=False → nullable=True
#   (agentless devices start unassigned)
```

Run migration:
```bash
cd api
flask db upgrade
```

### D.2 `api/utils/oui.py`

Static OUI → vendor lookup. No pip dependencies. 500+ entries.

```python
def lookup_vendor(mac: str) -> str:
    """Return vendor string for a MAC address, or 'Unknown'."""
    # Normalises mac, strips separators, upper-cases, slices first 6 chars (OUI prefix)
    # Looks up in a built-in dict of 500+ OUI → vendor name entries
```

### D.3 `api/tasks/network_tasks.py`

Key functions:

| Function | Description |
|----------|-------------|
| `_ping_host(ip)` | ICMP ping via `ping -n 1 -w 500` (Windows) or `-c 1 -W 1` (Unix). Returns bool. |
| `_get_mac_for_ip(ip)` | ARP table lookup (`arp -a`). Returns MAC string or `None`. |
| `_get_hostname(ip)` | Reverse DNS via `socket.gethostbyaddr(ip)[0]`. Returns hostname string (e.g. `iPhone.local`) or `None`. Runs **before** port probe so hostname is available for all fallbacks. |
| `_guess_platform(vendor)` | Heuristic: "Apple" → ios/mac, "Samsung/Google/OnePlus" → android, else unknown. |
| `_probe_platform(ip)` | Port probe fallback when OUI lookup returns unknown. Tries: 62078→iOS, 5555→Android, then **2+ of** (445, 3389, 139)→Windows (requires 2 to avoid misidentifying routers/NAS with only SMB), 548→macOS, 22→Linux. Skipped entirely for router hostnames. Returns `(platform, device_type)` or `("unknown", "unknown")`. |
| `_guess_platform_from_hostname(hostname)` | 3rd-stage fallback after OUI + port probe both fail. Matches 50+ keywords in rDNS hostname: Android brand names (samsung/galaxy/pixel/xiaomi/oneplus/huawei/oppo/vivo/realme/moto…) + Samsung model numbers (S10–S24, Note, A12–A73, Fold, Flip, Ultra); iOS keywords (iphone/ipad/ipod). Fritz!Box and most routers assign the device's advertised name. Returns `(platform, device_type)` or `("unknown", "unknown")`. |
| `run_network_scan(scan_id)` | Celery task. Parses CIDR, concurrent ping via `ThreadPoolExecutor(50)`, ARP MAC, OUI vendor, rDNS hostname, port probe, hostname keyword fallback; router hostnames are included in `discovered_hosts` for display but skipped from upsert; calls `_upsert_agentless_host` per non-router live IP, updates `NetworkScan` record. |
| `ping_agentless_devices()` | Beat task (300s). Loads all `is_agentless=True` devices, pings each, updates `is_online`/`last_seen`, batch commit. Devices silent for >10 min are marked offline. |
| `_upsert_agentless_host(ip, mac, vendor, platform, device_type, hostname=None)` | Internal helper. Lookup order: (1) MAC, (2) IP across ALL devices, (3) bare hostname match (strips .fritz.box/.local suffix, case-insensitive) — catches multi-adapter machines where agent/scan see different MACs. Upgrades `platform`/`device_type` on existing agentless records when re-scan detects better info. Never clobbers agent-managed (`is_agentless=False`) devices. |

### D.4 New API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/devices/platform_counts` | Returns `{"by_platform": {windows: N, ...}, "agentless": N}` |
| POST | `/api/devices/<id>/ping_check` | Pings device IP, updates `is_online`/`last_seen`. Only for `is_agentless=True` devices. |
| POST | `/api/network/agentless_devices` | Batch upsert. Body: `{"hosts": [...], "customer_id": optional}`. Returns `{"created": N, "updated": M, "skipped": K}`. |
| GET | `/api/admin/server_ips` | Returns `{"hostname": "...", "lan_ips": ["192.168.x.x"]}`. No auth required. |

`POST /api/network/scan` now wires `run_network_scan.delay(scan.id)` (was previously a stub).

### D.5 `agent/setup_agent.py`

CLI helper for WiFi deployment:

```bash
python setup_agent.py <server_lan_ip> <org_token>
```

Reads `config.ini`, updates `[api] url` and `[api] org_token`, clears `[agent] device_id` and `[agent] agent_token` so the agent re-registers cleanly on next start.

### D.6 Updated Dashboard Pages

**`dashboard/pages/04_Devices.py`** — Complete rewrite:
- 7 OS filter tabs: All | Windows | macOS | Linux | Android | iOS | Agentless (each with count badge)
- Loads all devices once + `platform_counts`; filters client-side per tab
- Agent device row: CPU/RAM/disk gauges, reboot/shutdown buttons, customer assign
- Agentless device row: IP, MAC, vendor badge, platform badge, last seen, online dot, Ping Now button, Edit button, Delete button, customer assign
- Edit button on agentless rows shows inline `st.form` with hostname (text_input), platform (selectbox), device_type (selectbox); calls `client.update_device(device_id, {...})` on submit. Workaround for randomized-MAC phones that port probing cannot identify.
- Duplicate widget key fix: `_render_agent_row(device, tab_key="")` and `_render_agentless_row(device, tab_key="")` accept `tab_key` param; all 11 widget keys inside those functions are prefixed with `tab_key` (e.g. `f"gauge_{tab_key}_{device['id']}"`). Render loop passes `tab_key=name` (the tab label string).
- Platform icons: windows=🪟 mac=🍎 linux=🐧 android=🤖 ios=📱 unknown=💻

**`dashboard/pages/07_Network_Discovery.py`** — Complete rewrite:
- Fixed bug: was calling GET on a POST-only route
- CIDR input (default `192.168.1.0/24`) + customer assignment dropdown
- Triggers `POST /api/network/scan`, polls `GET /api/network/scans/<id>` every 3s with spinner
- Results table: platform icon, IP, MAC, vendor, platform badge, status badge
- "Save All to Devices" button → `upsert_agentless_devices()`
- Idle state shows past scan history (last 5 scans)

**`dashboard/pages/10_Admin.py`** — Server IP card added:
- Calls `get_server_ips()`, displays each LAN IP as `st.code()` block (hover-to-copy)
- Step-by-step agent setup instructions with `setup_agent.py` usage example
- Collapsible "How to deploy agent on other WiFi machines" section

### D.7 New `api_client.py` Methods

| Method | HTTP | Path |
|--------|------|------|
| `get_platform_counts()` | GET | `/api/devices/platform_counts` |
| `ping_check_device(device_id)` | POST | `/api/devices/<id>/ping_check` |
| `upsert_agentless_devices(hosts, customer_id=None)` | POST | `/api/network/agentless_devices` |
| `trigger_network_scan(customer_id, scan_range)` | POST | `/api/network/scan` |
| `get_server_ips()` | GET | `/api/admin/server_ips` |
| `update_device(device_id, data)` | PUT | `/api/devices/<id>` |
| `delete_device(device_id)` | DELETE | `/api/devices/<id>` |

---

## Phase 5 — Dashboard Setup

### 5.1 Install deps

```bash
cd dashboard
python -m venv venv
venv\Scripts\activate
pip install streamlit plotly pandas requests python-dotenv
pip freeze > requirements.txt
```

### 5.2 `.streamlit/config.toml`

```toml
[server]
port = 8501
headless = true

[theme]
base = "dark"
primaryColor = "#407E3C"
backgroundColor = "#0e1117"
secondaryBackgroundColor = "#1a1f2e"
textColor = "#ffffff"
```

### 5.3 `dashboard/utils/nav.py` (shared sidebar, Phase B)

```python
import streamlit as st

def render_sidebar():
    """Render the shared sidebar with 5 nav sections."""
    user = st.session_state.get('user', {})
    # ... user card, role pill, 5 nav sections:
    # MONITORING: Overview, Devices, Alerts
    # MANAGEMENT: Tickets, Customers, Automation
    # PATCHING: OS Patches, Software Patches
    # TOOLS: Scripts, Disk Management, Maintenance, Network Discovery
    # BUSINESS: Reports, Billing, Admin
```

### 5.4 Dashboard pages (16 pages)

| File | Purpose |
|------|---------|
| `01_Dashboard.py` | Overview metrics, device health map, recent alerts, activity feed |
| `02_Tickets.py` | Create/view/update/assign/comment tickets |
| `03_Customers.py` | Customer CRUD, device count per customer |
| `04_Devices.py` | Device list with 7 OS filter tabs (All/Windows/macOS/Linux/Android/iOS/Agentless); agent devices show CPU/RAM/disk gauges + reboot/shutdown; agentless devices show IP, MAC, vendor badge, Ping Now button |
| `05_Alerts.py` | Alert rules config, active alerts, acknowledge/resolve |
| `06_App_Center.py` | Software inventory across devices |
| `07_Network_Discovery.py` | CIDR input, POST-triggered scan with 3s polling, results table (icon/IP/MAC/vendor/platform/status), Save All to Devices button, past scan history |
| `08_Reports.py` | Generate reports, download CSV |
| `09_Billing.py` | Invoice list, create invoice |
| `10_Admin.py` | User management (with "Require password change on first login" checkbox), audit logs, agent enrollment token (Reveal/Hide card) |
| `11_Automation.py` | Automation profile CRUD, run history |
| `12_OS_Patches.py` | OS patch status, approve, deploy patches |
| `13_Software_Patches.py` | Installed software inventory per device (registry + winget); `_clean()` sanitizer strips Unicode block chars before render |
| `14_Disk_Management.py` | Disk usage gauges, summary table, maintenance actions |
| `15_Maintenance.py` | Remote actions (reboot/shutdown/clean/restore/chkdsk/browser) with confirm gate |
| `16_Scripts.py` | Script library, run scripts on devices, view run history |

---

## Environment File

`.env`:
```env
DATABASE_URL=postgresql://rmm_app:changeme@localhost:5432/rmmdb
FLASK_ENV=development
FLASK_DEBUG=1
SECRET_KEY=<python -c "import secrets; print(secrets.token_hex(32))">
JWT_SECRET_KEY=<python -c "import secrets; print(secrets.token_hex(32))">
JWT_ACCESS_TOKEN_EXPIRES=900
JWT_REFRESH_TOKEN_EXPIRES=604800
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
ORG_REGISTRATION_TOKEN=<python -c "import secrets; print(secrets.token_hex(24))">
API_BASE_URL=http://localhost:5000
DASHBOARD_URL=http://localhost:8501
# Superadmin credentials (optional — override defaults)
SUPERADMIN_EMAIL=superadmin@rmm.local
SUPERADMIN_PASSWORD=SuperAdmin@RMM1
# SMTP (optional — omit to disable email alerts)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASS=your_app_password
SMTP_FROM=rmm@yourcompany.com
# AI Assistant
ANTHROPIC_API_KEY=sk-ant-api03-...
AI_ASSISTANT_MODEL=claude-haiku-4-5-20251001
AI_ASSISTANT_ENABLED=true
```

---

## Start Everything

Open 5 terminals:

**Terminal 1 — Flask API**
```bash
cd api ; venv\Scripts\activate ; python app.py
```

**Terminal 2 — Celery Worker**
```bash
cd api ; venv\Scripts\activate ; celery -A tasks.celery_app worker --pool=solo -l info
```

**Terminal 3 — Celery Beat** (scheduled tasks)
```bash
cd api ; venv\Scripts\activate ; celery -A tasks.celery_app beat -l info
```

**Terminal 4 — Dashboard**
```bash
cd dashboard ; venv\Scripts\activate ; streamlit run app.py
```

**Terminal 5 — Agent** (run as Administrator for patch scanning)
```bash
cd agent ; venv\Scripts\activate ; python rmm_agent.py
```

---

## Verify Health

```bash
curl http://localhost:5000/api/health      # → {"status": "ok"}
curl -s http://localhost:8501              # → 200
redis-cli ping                             # → PONG
psql -U rmm_app -d rmmdb -c "SELECT 1"    # → 1
```

---

## Port Kill (Windows)

```powershell
netstat -ano | findstr :5000
taskkill /F /PID <PID>
```

---

## Default Login

| Field | Value |
|-------|-------|
| URL | http://localhost:8501 |
| Email | admin@rmm.local |
| Password | Admin1234! |

Change password after first login.

---

## Security Checklist

- [ ] `.env` never committed (in `.gitignore`)
- [ ] `SECRET_KEY` and `JWT_SECRET_KEY` are random 32-byte hex strings
- [ ] `ORG_REGISTRATION_TOKEN` rotated after all agents registered (token visible in Admin → System Info → Agent Enrollment Token card)
- [ ] `rmm_app` DB user has no superuser privileges
- [ ] Rate limiting active on `/api/auth/login` (10/min)
- [ ] JWT tokens expire (900s access, 7d refresh)
- [ ] Agent tokens hashed before storing
- [ ] No `FLASK_DEBUG=1` in production
- [ ] `SMTP_PASS` is an app-specific password, not your Gmail password
- [ ] `api/reports/` directory not exposed via HTTP
- [ ] Superadmin default password changed (see Admin → Users or run `cd api ; python reset_superadmin.py <new_password>`)

---

## Key Architecture Decisions

| Decision | Reason |
|----------|--------|
| Flask + SQLAlchemy | Simple, well-known, easy to extend |
| PostgreSQL over SQLite | Production-grade, concurrent writes |
| Celery + Redis | Async tasks for long-running ops (defrag, reports, patch deploy) |
| Streamlit dashboard | Rapid UI with minimal JS |
| JWT auth | Stateless, works for API + dashboard |
| `pool=solo` Celery | Windows has no `fork()` |
| Hardware fingerprint = SHA256(hostname+MAC) | Unique device ID without agent install key |
| bcrypt rounds=12 | Balance security vs login latency |
| Built-in scripts as Script records | Avoids new DB migration; reuses existing ScriptRun task queue |
| `file_path` on Report | Dashboard and API on same machine; bytes read directly — no file serving needed |
| SMTP gated on env var | Email optional; missing config silently skips, no crash |
| Superadmin always-present | Emergency lockout recovery without out-of-band DB access |

---

## Phase E — AI Assistant

### What it does

Embeds a context-aware AI chat widget in every dashboard page. Users type natural-language questions ("How do I deploy patches?", "What does a critical alert mean?") and receive step-by-step guidance tailored to their current page and role.

### New files

| File | Purpose |
|------|---------|
| `api/routes/assistant.py` | Flask blueprint — `POST /api/assistant/chat` (JWT required, 30 req/min) |
| `dashboard/utils/ai_assistant.py` | Streamlit sidebar widget — `render_ai_assistant(page_name, context)` |

### `api/routes/assistant.py` — key design

- `_PAGE_INFO` dict: description of every page injected into system prompt
- `_ROLE_CAPABILITIES` dict: what each role can do — AI never suggests actions above the user's role
- `_PAGE_ACTIONS` dict: 2–3 suggested quick-action buttons per page
- `_build_system_prompt(role, page, context)` assembles the final system prompt
- `chat()` endpoint: validates JWT → extracts role via `get_jwt().get("role", "viewer")` (not `get_jwt_identity()`) → calls Anthropic SDK → returns `{reply, suggested_actions}`

> **Critical:** JWT role lives in `additional_claims`, not the identity. Always use `get_jwt()` to read it.

### `dashboard/utils/ai_assistant.py` — key design

- Builds `RMMClient` directly from `st.session_state["access_token"]` — does NOT rely on `st.session_state["_rmm_client"]` (that key is never set)
- Session state keys: `_ai_history`, `_ai_open`, `_ai_seen_onboard`, `_ai_suggested`
- First login: auto-opens on Overview page, shows welcome message, sets `_ai_seen_onboard = True`
- All widget keys scoped to `page_key` (lowercased page name) to prevent cross-page key conflicts

### How to call on each page

```python
from utils.ai_assistant import render_ai_assistant

# Minimal call (most pages)
render_ai_assistant("Page Name")

# Rich call with live data (data-heavy pages)
render_ai_assistant("Alerts", {
    "open_alerts": open_count,
    "critical_alerts": crit_count,
    "acknowledged_alerts": ack_count,
})
```

### Install dependency

```bash
cd api
venv\Scripts\activate
pip install anthropic>=0.40.0
pip freeze > requirements.txt
```

### Required `.env` vars

```
ANTHROPIC_API_KEY=sk-ant-api03-...
AI_ASSISTANT_MODEL=claude-haiku-4-5-20251001
AI_ASSISTANT_ENABLED=true
```

Set `AI_ASSISTANT_ENABLED=false` to disable without removing the widget code.

### Architecture note

| Decision | Reason |
|----------|--------|
| API key server-side only | Dashboard never touches the key; zero client exposure |
| JWT auth on `/api/assistant/chat` | AI respects same role system as every other endpoint |
| Rate limit 30 req/min | Prevents abuse; reuses existing Flask-Limiter |
| History in session state only | No PII stored in DB; GDPR-friendly |
| Claude Haiku 4.5 | <1s typical response; ~$0.0008/query at normal usage |

---

## Phase F — Commercial Audit (Security, Scale, Compliance)

### F.1 Agent Multi-Customer Routing

`agent/config.ini` — add under `[api]`:
```ini
customer_id =
```

`api/schemas/agents.py` — add field:
```python
customer_id = fields.String(load_default="", validate=validate.Length(max=36))
```

`api/routes/agents.py` — replace hardcoded first-customer lookup:
```python
customer_id_hint = data.get("customer_id", "").strip()
if customer_id_hint:
    customer = Customer.query.filter_by(id=customer_id_hint, is_active=True).first()
    if not customer:
        return jsonify({"error": "Invalid customer_id"}), 400
else:
    customer = Customer.query.filter_by(is_active=True).first()
```

Deploy new agent via `setup_agent.py`:
```bash
python setup_agent.py <server_ip> <org_token> <customer_id>
```

---

### F.2 Agent Token DPAPI Encryption (Windows)

`agent/rmm_agent.py` — helpers after `save_config()`:
```python
_IS_WINDOWS = platform.system() == "Windows"
_DPAPI_PREFIX = "DPAPI:"

def _protect_token(plaintext: str) -> str:
    if not _IS_WINDOWS or not plaintext:
        return plaintext
    import win32crypt, base64
    blob = win32crypt.CryptProtectData(plaintext.encode("utf-8"), "RMM Agent Token", ...)
    return _DPAPI_PREFIX + base64.b64encode(blob).decode("ascii")

def _unprotect_token(stored: str) -> str:
    if not stored.startswith(_DPAPI_PREFIX):
        return stored  # legacy plaintext — migrated automatically on next save
    import win32crypt, base64
    raw = base64.b64decode(stored[len(_DPAPI_PREFIX):])
    _, plaintext = win32crypt.CryptUnprotectData(raw, ...)
    return plaintext.decode("utf-8")
```

On startup, reads stored token through `_unprotect_token`. On register/rotate, saves through `_protect_token`.

---

### F.3 OpenAPI / Swagger Documentation

New files:
- `api/swagger_spec.py` — Python dict with full OpenAPI 3.0 spec (47 paths, 16 tag groups, BearerAuth scheme)
- `api/routes/docs.py` — Blueprint serving:
  - `GET /api/docs` — SwaggerUI HTML (CDN, `#407E3C` brand topbar)
  - `GET /api/openapi.json` — raw spec

Register in `api/app.py`:
```python
from routes.docs import docs_bp
app.register_blueprint(docs_bp)  # no url_prefix — routes are absolute
```

No new pip dependencies. SwaggerUI loads from CDN.

---

### F.4 Redis Query Cache

`api/utils/cache.py`:
```python
def cache_get(key: str): ...       # returns deserialized value or None
def cache_set(key: str, value, ttl: int): ...  # stores JSON with TTL
def cache_delete(key: str): ...    # deletes key
```

Applied in:
- `api/routes/dashboard.py` `summary()` — 30s TTL, key `rmm:dash:summary:{cid or 'all'}`
- `api/routes/devices.py` `platform_counts()` — 60s TTL, key `rmm:dash:platform_counts`

---

### F.5 Alert Webhook Dispatch

`api/utils/webhook.py`:
```python
def dispatch_alert_webhooks(channels, rule_name, device_hostname, message, severity):
    if channels.get("slack"): _post_slack(...)
    if channels.get("teams"): _post_teams(...)
    if channels.get("webhook"): _post_generic(...)
```

Payloads:
- **Slack** — Block Kit attachment with color-coded severity (#FF3B30 critical, #FF9500 warning, #007AFF info)
- **Teams** — MessageCard format
- **Generic** — `{"event":"rmm_alert","rule":...,"device":...,"severity":...,"message":...,"timestamp":...}`

Add webhook URL to `AlertRule.notification_channels`:
```json
{"email": ["ops@example.com"], "slack": "https://hooks.slack.com/...", "teams": "https://outlook.office.com/..."}
```

---

### F.6 Nightly Database Backup

`api/tasks/backup_tasks.py`:
- Finds `pg_dump` (PATH or Windows install paths `/Program Files/PostgreSQL/*/bin/`)
- Runs dump, gzip-compresses to `BACKUP_DIR` (default: `../backups/`)
- Prunes `.sql.gz` files older than `BACKUP_RETAIN_DAYS` (default 7)
- Retries on timeout (1h) or error (30 min)

Beat schedule entry in `celery_app.py`:
```python
"backup-database-daily": {"task": "tasks.backup_tasks.backup_database", "schedule": 86400.0}
```

Env vars:
```
BACKUP_DIR=C:\RMM\backups
BACKUP_RETAIN_DAYS=7
```

Restore:
```bash
gunzip -c backups/rmmdb_20260713_020000.sql.gz | psql -U rmm_app rmmdb
```

---

### F.7 Billing Automation

Customer model — new columns:
```python
billing_day     = db.Column(db.Integer, nullable=True)      # day-of-month (1-28)
per_device_rate = db.Column(db.Numeric(10, 2), nullable=True)
tax_rate        = db.Column(db.Numeric(5, 4), nullable=True)  # 0.0800 = 8%
```

Migration: `j1k2l3m4n5o6`

`api/tasks/billing_tasks.py` `generate_recurring_invoices`:
- Runs daily via beat (86400s)
- Finds customers where `billing_day == today` and `per_device_rate > 0`
- Generates draft invoice for prior calendar month
- Idempotent — skips if invoice for that `(customer_id, period_start)` already exists

Configure billing profile via `PUT /api/customers/<id>`:
```json
{"billing_day": 1, "per_device_rate": 15.00, "tax_rate": 0.08}
```

---

### F.8 Configurable SLA Policies

`api/models/sla_policy.py` — `SLAPolicy` model: `customer_id` (nullable = global), `priority`, `response_hours`, `resolution_hours`. Unique constraint on `(customer_id, priority)`.

Migration `k2l3m4n5o6p7` — creates table + seeds 4 global defaults:

| Priority | Response | Resolution |
|----------|----------|------------|
| critical | 1h | 4h |
| high | 4h | 8h |
| medium | 8h | 24h |
| low | 24h | 72h |

CRUD at `/api/sla-policies/`:
- `GET /` — list policies (filter by `?customer_id=` for combined global + customer view)
- `POST /` — create (admin only)
- `PUT /<id>` — update hours (admin only)
- `DELETE /<id>` — delete customer-specific only; global defaults protected

Ticket creation lookup order:
1. Customer-specific policy for `(customer_id, priority)`
2. Global policy for `priority`
3. Hardcoded fallback `_SLA_HOURS`

---

### F.9 GDPR Endpoints

```
GET    /api/admin/users/<id>/gdpr-export   # Art. 20 — data portability
DELETE /api/admin/users/<id>/gdpr-delete   # Art. 17 — right to erasure (irreversible)
```

Export returns: `{user, audit_log (last 1000), ticket_comments (last 1000)}`.

Delete anonymizes:
- `user.email` → `__anon__<id8>@deleted.local`
- `user.full_name` → `Deleted User <id8>`
- `user.password_hash` → `""`
- `user.avatar_data` → `None`
- `TicketComment.author_email` → `None` for all their comments
- `AuditLog.ip_address` → `"0.0.0.0"` for all their log entries

Both endpoints are admin-only. Both emit their own `AuditLog` entry.

---

### F.10 New Environment Variables

Add to `.env`:
```
# Backup
BACKUP_DIR=../backups
BACKUP_RETAIN_DAYS=7

# Alert webhooks (per AlertRule notification_channels — not global .env vars)
# Set per-rule in the Alerts UI

# Billing (per customer via API — not global)
```

---

## Phase G — Mobile Device Management (Android Management API)

Real phone management (lock/wipe/lost-mode/compliance) with no custom agent installed on the device. Android runs Google's own signed "Android Device Policy" app, provisioned via a device-owner-initiated QR/link enrollment (never silent — required by Google and by consent law for BYOD). iOS is not implemented — see G.7.

### G.1 Database Migration

Migration file: `api/migrations/versions/o6p7q8r9s0t1_mdm_integrations.py`
Chains after: `n5o6p7q8r9s0`

New tables:

```python
class MdmIntegration(db.Model):        # mdm_integrations
    type = db.Column(db.String(20))     # "android" now, "apple" reserved for later — no migration needed then
    customer_id = db.Column(db.String(36), nullable=True)   # null = staff-wide
    project_id, enterprise_id           # Google Cloud project + bound enterprise resource name
    service_account_json_enc            # Fernet-encrypted, never written to disk
    apple_push_cert_enc, apple_topic    # unused placeholders for a future iOS phase

class MobileEnrollment(db.Model):      # mobile_enrollments — one-to-zero-or-one with Device
    device_id = db.Column(db.String(36), unique=True, nullable=True)
    ownership_type = db.Column(db.String(20))  # byod | corporate → allowPersonalUsage
    status = db.Column(db.String(20))          # pending | enrolled | revoked | wiped | expired
    consent_given_by_user_id, consent_given_at, consent_text_version, consent_ip_address
    #   real columns, not a JSON blob — this IS the legal consent record
```

`Device` gets zero new columns — `Device.mdm_enrollment` is a relationship. `Device.is_agentless` stays `True` for managed phones (still no RMM agent runs); real action buttons gate on `device.mdm_enrollment.status == "enrolled"` instead.

Run migration:
```bash
cd api
flask db upgrade
```

### G.2 `api/utils/crypto.py`

Promoted out of `api/models/psa_integration.py` so both `PsaIntegration` and `MdmIntegration` share one Fernet implementation instead of duplicating it.

```python
def encrypt_cred(value: str) -> str: ...   # Fernet, key = SHA-256(SECRET_KEY)
def decrypt_cred(value: str) -> str: ...
```

### G.3 `api/utils/android_mgmt.py`

Thin REST client over Google's Android Management API. New dependency: `google-auth>=2.30.0` in `api/requirements.txt`.

| Function | Description |
|----------|-------------|
| `create_signup_url(callback_url)` | Step 1 of enterprise binding. Callback must be a real HTTPS URL — Google rejects `localhost`. |
| `create_enterprise(signup_url_name, enterprise_token, display_name)` | Step 2, called from the `bind_callback` route once Google redirects back. |
| `patch_policy(policy_name, policy)` | Pushes a policy JSON to `enterprises/{id}/policies/{name}`. |
| `create_enrollment_token(policy_name, ttl_hours, allow_personal_usage)` | Returns `{value, qrCode, expirationTimestamp}` — `qrCode` is a JSON string meant to be rendered as a QR image. |
| `list_devices()` | `enterprises.devices.list` — used by the sync task. |
| `issue_command(device_name, command_type, **extra)` | `LOCK \| RESET_PASSWORD \| REBOOT \| WIPE \| START_LOST_MODE \| STOP_LOST_MODE \| RELINQUISH_OWNERSHIP`. Returns immediately — applies on next device check-in. |
| `delete_device(device_name, wipe_data_flags=None)` | Removes a device from the enterprise. |

### G.4 `api/routes/mobile_mdm.py` — New API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/mdm/integrations` | Create integration stub (admin) |
| POST | `/api/mdm/integrations/<id>/credentials` | Multipart upload of service-account JSON (admin) |
| POST | `/api/mdm/integrations/<id>/bind` | Returns `{signup_url}` (admin) |
| GET | `/api/mdm/integrations/<id>/bind_callback` | Google's redirect target, validated via a cached state nonce, not JWT |
| PUT | `/api/mdm/integrations/<id>/policy` | Push policy JSON (admin, technician) |
| GET | `/api/mdm/available_integrations` | Secret-free list scoped to caller's customer — feeds the Client Portal enrollment dropdown |
| POST | `/api/mdm/enrollments` | Create enrollment token. `role=client` forced to `ownership_type=byod`, requires `consent_acknowledged=true`, 404s on a foreign-customer integration |
| DELETE | `/api/mdm/enrollments/<id>` | Revoke — `RELINQUISH_OWNERSHIP` (BYOD) or full removal (corporate) |
| POST | `/api/mdm/devices/<id>/lock` \| `/reboot` \| `/reset_password` \| `/wipe` \| `/start_lost_mode` \| `/stop_lost_mode` | Issues the matching command. `wipe` is admin-only. `lock`/`start_lost_mode`/`stop_lost_mode` are the only ones a `role=client` may call, on their own device only. |

Every mutating route calls `_mdm_scope_check()` — same pattern as `devices.py`'s `_client_scope_check()` from the earlier cross-tenant-leak fix.

### G.5 `api/tasks/mdm_tasks.py`

| Function | Description |
|----------|-------------|
| `sync_all_mdm_integrations()` | Beat task (300s). Fans out `.delay()` per active, bound `MdmIntegration`. |
| `sync_mdm_integration(mdm_integration_id)` | Calls `enterprises.devices.list`, matches new devices to pending `MobileEnrollment`s, creates the `Device` row on first sight, updates `policy_compliant`/hardware fields every pass. Same shape as `tasks.psa_tasks.sync_all_psa_integrations`. |

Registered in `celery_app.py`: `include=[..., "tasks.mdm_tasks"]`, `beat_schedule["mdm-sync-every-5-min"] = {"task": "tasks.mdm_tasks.sync_all_mdm_integrations", "schedule": 300.0}`.

### G.6 Updated Dashboard Pages

**`dashboard/pages/19_Mobile_Enrollment.py`** — new page (admin/technician):
- Android tab: integration list (upload credentials, start binding, push policy JSON), "Add integration" form, enrollment generator (QR rendered with the `qrcode` package — same approach as MFA setup in `17_Profile.py`), enrollments list with Revoke
- iOS tab: static explainer of why it's not implemented (Apple Business Manager / Fleet-MicroMDM decision required)

**`dashboard/pages/04_Devices.py`** — dispatch updated:
- New `_render_mobile_managed_row(device, tab_key)`: Lock / Lost Mode / Reboot / Reset Passcode / Wipe (2-step confirm) buttons
- Render loop checks `device.mdm_enrollment.status == "enrolled"` **before** the existing `is_agentless` check, so managed phones get the new row instead of the old "no agent" notice

**`dashboard/pages/21_Client_Tickets.py`** — new "+ Enroll My Phone" expander:
- Plain-language consent disclosure text, checkbox gates QR generation
- Calls `GET /api/mdm/available_integrations` (client-safe) then `POST /api/mdm/enrollments` with `ownership_type="byod"`

**`dashboard/utils/nav.py`** — new sidebar link under Tools, admin/technician only: `pages/19_Mobile_Enrollment.py`

### G.7 iOS status

Not implemented. Real Apple MDM needs an APNs push certificate, which Apple only counter-signs for Apple Business Manager-enrolled orgs or already vendor-signed MDM servers (Fleet, MicroMDM/NanoMDM) — a business/account decision outside this codebase, not a code gap. `MdmIntegration.type` already accepts `"apple"`; `apple_push_cert_enc`/`apple_topic` columns already exist (G.1); `MdmIntegration.get_client()` has an `elif self.type == "apple": raise NotImplementedError(...)` stub. Whichever path is chosen later needs only that one branch filled in — no new migration, no route/table rearchitecture.

### G.8 New Environment Variables

Add to `.env.example` (see full comment block there — real credentials are uploaded via dashboard into the encrypted DB column, never here):
```
# === Mobile Device Management (Android) ===
# No secrets go here — Google service-account JSON is uploaded via
# Admin -> Mobile Enrollment and stored encrypted in the DB.
# Requires: google-auth>=2.30.0 in api/requirements.txt
```

## Phase H — AI Assistant Services Refactor + API/Token Usage Monitoring

Two related pieces of work: (1) moving the AI Assistant's prompt/tool logic into a proper services layer with durable conversation history, and (2) a superadmin-only feature to see and control API/AI-token usage after it grew unexpectedly high with no visibility into the cause.

### H.1 AI Assistant refactor — `api/services/`

Extract everything out of `routes/assistant.py` that isn't route-handling:

```python
# api/services/ai_prompt.py
_PAGE_INFO = {...}              # per-page description injected into the system prompt
_ROLE_CAPABILITIES = {...}      # per-role capability summary
_PAGE_ALLOWED_ROLES = {...}     # server-side 403 BEFORE calling Claude — not just prompt text.
                                 # Pages not listed here are reachable by any authenticated role.
_RESTRICTED_PAGES = {...}       # nav-only mode, code blocks stripped from replies
_DANGER_PATTERNS = [...]        # regexes that trigger a CAUTION banner
def build_system_prompt(role, page, context, agentic): ...

# api/services/ai_tools.py
TOOL_DEFINITIONS = [...]        # Claude tool-use schema
READ_TOOLS, MUTATING_TOOLS = {...}, {...}
_TOOL_RATE_LIMITS = {"run_script": (5, 60), ...}   # (limit, window_seconds) per tool
def tools_for_page(page, agentic): ...
def execute_read_tool(name, input, ctx): ...        # dispatches to *_service.py
def stage_mutating_tool(name, input, ctx, conv_id, tool_use_id): ...   # creates AiPendingAction, never executes
def execute_pending_action(action_id, ctx): ...      # re-derives ctx from the CURRENT JWT at confirm-time
```

Business logic the tools call into (generic, reusable, no Anthropic dependency): `alert_service.py`, `script_service.py`, `ticket_service.py`, `fleet_query_service.py`, `device_query_service.py`.

### H.2 Conversation persistence — migration `p7q8r9s0t1u2`

```python
class AiConversation(db.Model):   # ai_conversations — one active per (user_id, page)
    user_id, page, is_archived, created_at, updated_at

class AiMessage(db.Model):        # ai_messages
    conversation_id, role, content, tool_calls (JSON), contains_warning, created_at

class AiPendingAction(db.Model):  # ai_pending_actions — staged mutating tool call
    conversation_id, user_id, tool_name, tool_input (JSON), tool_use_id, summary,
    contains_warning, status (pending|confirmed|denied|expired|failed), result (JSON),
    expires_at, resolved_at
```

New routes: `POST /api/assistant/actions/<id>/confirm`, `POST /api/assistant/actions/<id>/deny` — a staged mutating call sits until one of these is hit or `expires_at` passes (`AI_ASSISTANT_ACTION_TTL_SECONDS`, default 300s).

### H.3 `api/utils/rate_limit.py`

```python
def check_and_increment(key: str, limit: int, window_seconds: int) -> bool:
    """Redis INCR+EXPIRE. Returns True if under limit (and increments). Fails OPEN if Redis is down."""
```

Needed because tool execution calls service functions **directly**, bypassing Flask-Limiter's route decorators — this is the per-user/per-tool limiter for that path.

### H.4 Usage Monitoring — why

Not a feature anyone asked for in the abstract — it was built because usage (API calls, and especially AI tokens) had grown unexpectedly high with zero visibility into which service, page, or user was responsible. Requirement: visible to the Super Administrator **only** — not even a regular Admin.

### H.5 Database — migration `q8r9s0t1u2v3` (chains after `p7q8r9s0t1u2`)

```python
class ApiUsageEvent(db.Model):     # api_usage_events — one row per instrumented call
    service      # ai_assistant | stripe | psa_connectwise | psa_autotask | android_mdm |
                 # email_imap | network_scan | webhook_slack/teams/generic | smtp
    feature, user_id (nullable — null = system/celery-triggered)
    input_tokens, output_tokens, estimated_cost_usd   # only populated for ai_assistant
    status, status_code, latency_ms
    error_message   # truncated exception text ONLY — never a raw response body/header/secret
    created_at
    # Index (service, created_at) for aggregation queries

class ApiUsageHourly(db.Model):    # api_usage_hourly — durable rollup, NOT one row per request
    bucket_start, endpoint, method, request_count, error_count, total_latency_ms
    # UniqueConstraint(bucket_start, endpoint, method)

class UsageAlertConfig(db.Model):  # usage_alert_config — singleton row, id="default"
    is_enabled, spike_multiplier (default 3.0), notification_channels (JSON, same shape as AlertRule's)
    # Deliberately its OWN table, NOT an AlertRule row — an AlertRule row would be
    # visible to admin/technician via the Alerts page, leaking this feature's existence.
```

### H.6 `api/utils/usage_tracker.py` — the one shared utility

```python
def record_event(service, feature=None, user_id=None, input_tokens=None, output_tokens=None,
                  status="success", status_code=None, latency_ms=None, error=None, model=None):
    """Writes one ApiUsageEvent row. FAILS OPEN — never raises. Computes estimated_cost_usd
    from AI_ASSISTANT_COST_PER_1M_INPUT/_OUTPUT when tokens are given and the model matches."""

def record_internal_api_call(endpoint, method, status_code, latency_ms):
    """Redis HINCRBY on rmm:usage:hourly:{YYYYMMDDHH} — too high-volume for one DB row/request.
    Called from api/app.py's EXISTING _log_request after_request hook (reuses its duration_ms)."""

def compute_anomalies(spike_multiplier=3.0):
    """Compares the last COMPLETED hour per service against the trailing-7-day
    same-hour-of-day average. Shared by the /summary endpoint AND the beat task below —
    one implementation, not two that could drift."""
```

Instrumentation call sites (same `record_event(...)` pattern at each): both `client.messages.create()` calls in `routes/assistant.py` (reads `resp.usage` — guard with `getattr(resp, "usage", None)` first, since test mocks and possibly some SDK paths won't have it), `utils/webhook.py::_send`, `utils/notifications.py::_smtp_send` + `routes/billing.py`'s invoice-email block, `utils/stripe_client.py`, `utils/android_mgmt.py::_request`, `utils/psa/connectwise.py` + `utils/psa/autotask.py` (`_get`/`_post`/`_patch`/`_put`), `tasks/email_tasks.py::poll_support_inbox` (one event per run, not per message), `tasks/network_tasks.py` (one event per scan run, not per host — too granular).

### H.7 `api/routes/usage.py` — `/api/admin/usage`, superadmin ONLY

```python
def _require_superadmin():
    # UNLIKE every other route file's _require_role(), this has NO admin bypass:
    if get_jwt().get("role") != "superadmin":
        return jsonify({"error": "Super Administrator access required"}), 403
```
Routes: `GET /summary?range=today|7d|30d`, `GET /timeseries?range=&service=&metric=calls|tokens|cost`, `GET /by-feature?range=&service=`, `GET /events?service=&status=&page=`, `GET`/`PUT /alert-config`.

### H.8 `api/tasks/usage_tasks.py` — two new hourly beat entries

```python
persist_hourly_usage_rollup()   # reads the PREVIOUS hour's Redis hash, upserts into ApiUsageHourly
detect_usage_anomaly()          # if UsageAlertConfig.is_enabled: compute_anomalies() then call
                                 # send_alert_notification()/dispatch_alert_webhooks() DIRECTLY with
                                 # device_hostname="System / API Usage" — NO Alert/AlertRule row
                                 # created (Alert.device_id is NOT NULL; not worth migrating for this)
```
Add both to `celery_app.py`'s `beat_schedule` (3600.0s each) and `"tasks.usage_tasks"` to `include=[...]`.

### H.9 Retention + Reports integration

`tasks/maintenance_tasks.py::prune_old_data` — add `ApiUsageEvent` (90-day cutoff) and `ApiUsageHourly` (180-day cutoff) to the existing delete-and-count pattern.

`tasks/report_tasks.py` — new `"api_usage"` branch in `_collect_data()`. `routes/reports.py` — hide the `api_usage` template from list/generate/get for any non-superadmin (`_SUPERADMIN_ONLY_TEMPLATES = ("api_usage",)`).

### H.10 UI — both surfaces, superadmin-only exactly

`dashboard/pages/22_Usage_Monitoring.py` + `frontend/src/pages/UsageMonitoringPage.tsx` — guard is `role != "superadmin"` (not `not in ("admin", "superadmin")` like every other admin page). Nav entry in its own gated block in both `dashboard/utils/nav.py` and `frontend/src/components/Layout.tsx` (`roles: ['superadmin']`), never folded into an existing `("admin", "superadmin")` conditional.

### H.11 New Environment Variables

```
AI_ASSISTANT_COST_PER_1M_INPUT=1.00
AI_ASSISTANT_COST_PER_1M_OUTPUT=5.00
# $ per 1M tokens for the configured AI_ASSISTANT_MODEL — drives the "Estimated cost"
# figure on the superadmin Usage Monitoring page/report only. Not authoritative billing data.
```

### H.12 Tests

`api/tests/test_assistant.py` (14 tests) — kill switches, page auth, tool dispatch, confirm/deny staging, danger-pattern detection, persistence. `api/tests/test_usage.py` (13 tests) — RBAC (admin → 403 on every route, superadmin → 200), `record_event` cost calculation, `compute_anomalies` threshold logic, hourly rollup persistence (mock Redis via `patch("utils.cache._get_client", ...)`), retention pruning. Full suite: 146/146 passing.

---

## Phase I — Code Quality, Test Coverage, and Security Remediation

Three sequential audit-and-fix passes over the whole codebase (`audits/code_duplication_audit.md`, `audits/testing_audit.md`, `audits/security_audit.md`, each with a "Remediation Status" section listing every fix). Recreate this phase by running each audit's methodology and applying its fixes in order — duplication first (it makes the codebase easier to test), then test coverage (it will find real bugs), then security (some of what it fixes was found by the coverage pass).

### I.1 Consistent pagination — `api/utils/pagination.py`

```python
def paginated_response(query, serialize, *, order_by=None, default_per_page=50,
                        max_per_page=200, items_key="items"):
    """query: unfiltered/unordered SQLAlchemy Query. serialize: row -> dict.
    Reads page/per_page from flask.request.args, clamps per_page to max_per_page.
    Returns {items_key: [...], "total": N, "page": N, "pages": N}."""
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", default_per_page, type=int), max_per_page)
    if order_by is not None:
        query = query.order_by(order_by)
    p = query.paginate(page=page, per_page=per_page, error_out=False)
    return {items_key: [serialize(row) for row in p.items],
            "total": p.total, "page": p.page, "pages": p.pages}
```

Wire into every list endpoint that returns a paginated collection:
```python
return jsonify(paginated_response(Thing.query.filter_by(customer_id=cid),
                                   lambda t: t.to_dict(), order_by=Thing.created_at.desc()))
```

Migrating an existing hand-rolled pagination block: check the response key it currently uses (`"items"` vs. something else) before swapping — a real live bug came from exactly this: one endpoint returned `"users"` while its consumer read `data.items`.

### I.2 Test coverage — one test file per module, no exceptions

Target: every file in `api/routes/`, every file in `api/tasks/`, every file in `dashboard/pages/`, every file in `frontend/src/pages/` has a dedicated test file. Practical order that worked well: routes first (fastest feedback, most straightforward — JWT fixture + HTTP call + assert), then Celery tasks (need `tasks._app_singleton._app = app` primed and heavy external-I/O mocking — subprocess, IMAP, SNMP, MQTT, third-party PSA/MDM clients), then dashboard pages (`streamlit.testing.v1.AppTest`, needs `patch("streamlit.page_link")`/`patch("streamlit.switch_page")` in every file since `AppTest.from_file()` can't resolve the multipage registry on an isolated page), then frontend pages (Vitest + React Testing Library, needs installing first — see below).

```bash
# api/.coveragerc — exclude tests/migrations/seed.py from the coverage denominator,
# otherwise every test file's own ~100% self-coverage inflates the real number
[run]
omit = tests/*, migrations/*, seed.py
```

```bash
cd frontend
npm install -D vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom
npm install -D @playwright/test && npx playwright install --with-deps chromium
```
```ts
// vite.config.ts — Vitest reads this file directly, no separate config needed
test: { environment: "jsdom", globals: true, setupFiles: "./src/test/setup.ts", exclude: ["e2e/**"] }
```

CI: add `--cov-fail-under=70` to the pytest step (raise as real coverage grows), add `test-dashboard` (`ubuntu-latest`, pure Python) and `test-agent` (`windows-latest` — `pywin32`/`wmi` need Windows) jobs if they don't already exist.

**Expect to find real bugs while writing tests, not just missing coverage** — the highest-value one in this pass was a `dashboard/utils/cached_calls.py` cross-session cache leak (see I.3). Treat every "that assertion shouldn't have failed" moment as a signal to investigate the production code, not just the test.

### I.3 The `st.cache_data` underscore-parameter trap

Any `@st.cache_data`-wrapped function whose parameter name starts with `_` has that parameter **silently excluded from the cache key** — Streamlit's documented behavior for "uncacheable" params, but a trap when the excluded param is the thing that scopes the cached result to one user (an access token, a user ID). Confirmed with a standalone repro:
```python
@st.cache_data(ttl=60)
def cached_fn(_token):
    return call_api(_token)
cached_fn("token-A")   # caches under a key that ignores _token
cached_fn("token-B")   # returns token-A's cached result — WRONG
```
Fix: never underscore-prefix a parameter that should be part of the cache key. If a param genuinely shouldn't be hashed (e.g. a non-hashable client object), keep the underscore but make sure nothing user-scoped rides along with it — or pass a plain hashable proxy (a token string) instead.

### I.4 Security fixes — pattern reference

| Issue | Pattern |
|---|---|
| Fail-open crypto helper | Never `except Exception: return value` around encrypt/decrypt — let it raise into the app's existing generic error handler. |
| Sensitive column stored in plaintext | Add `set_x()`/`get_x()` methods on the model that route through the existing shared `crypto.py` helper — don't write a second encryption implementation. |
| Encryption key with no domain separation | Hash a fixed context-prefix string plus the shared secret (`SHA256("my-purpose:" + SECRET_KEY)`), not the shared secret alone. |
| Replayable single-use token | Compare the token's `iat` claim against a "last invalidated at" timestamp column that's already being set elsewhere as a side effect (e.g. `password_changed_at`) — no new column or denylist needed. Watch for naive-vs-aware datetime comparison bugs when the column comes back from SQLite as naive. |
| Missing security headers | Add to the app's *existing* `after_request` hook rather than a new one; carve out a scoped exception for any page that legitimately needs a relaxed CSP (e.g. a CDN-loaded docs UI) instead of disabling it globally. |
| Unescaped user-controllable field in `unsafe_allow_html=True` markup | Audit every such block for 100% field coverage by the existing `esc()`/escaping convention — one missed field in one block is enough for stored XSS. Add a regression test asserting a `<img onerror=...>`-style payload renders as escaped entities. |
| Dependency vulnerability backlog | Don't assume it's a big project — run `pip-audit`/`npm audit` for real, package by package, before scoping. Most fixes are patch/minor bumps. Isolate genuinely blocked packages (a hard version-compatibility conflict, confirmed by direct test) and document them explicitly (`--ignore-vuln` + a comment explaining exactly why, in both `requirements.txt` and CI) rather than leaving CI's vulnerability scan as `continue-on-error: true` indefinitely. |
| Unpinned dependency upper bound | Cap at the next major version above what's currently installed, matching whatever convention already exists elsewhere in the same requirements file. |

### I.5 Verification discipline

Every fix in this phase was re-verified after making it — full test suite re-run (sometimes 2-3 times to catch order-dependent flakiness from the shared session-scoped test DB), and the highest-risk fixes (MFA encryption, crypto key change, dependency major-version bumps) were additionally smoke-tested against the real running Postgres/Redis stack, not just the SQLite-backed test suite — e.g. a full MFA setup→enable→login round trip confirming real Fernet ciphertext in the live DB column, not just a passing unit test.
