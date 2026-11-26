"""Every environment variable the Python code reads (api/, dashboard/, agent/, scripts) is documented in the root
.env.example, and nothing is listed there that nothing reads. Add a setting: read it in the code, then add it to
.env.example (commented out with its default if it is optional). The React app's VITE_* settings live in
frontend/.env.example and are not checked here."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {"tests", "venv", ".venv", "node_modules", ".git", "__pycache__", "frontend"}
READ = re.compile(r"""(?:os\.environ\.get|os\.getenv|os\.environ\[|environ\)\.get|\bget_model)\(?\s*["']([A-Z][A-Z0-9_]*)["']""")
# Listed in .env.example but read outside the Python code.
READ_ELSEWHERE = {"REDIS_PASSWORD"}  # docker-compose.yml
# Read by the code but deliberately not listed: old names kept working for existing setups.
OLD_NAMES = {"SMTP_PASS"}  # use SMTP_PASSWORD


def _code_reads():
    names = {}
    for path in ROOT.rglob("*.py"):
        if SKIP_DIRS & set(path.relative_to(ROOT).parts):
            continue
        for name in READ.findall(path.read_text(encoding="utf-8", errors="replace")):
            names.setdefault(name, str(path.relative_to(ROOT)))
    return names


def _example_names():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    return set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]*)=", text, flags=re.M))


def test_the_scan_finds_the_settings():
    reads = _code_reads()
    assert {"DATABASE_URL", "SMTP_PASSWORD", "AI_ASSISTANT_MODEL", "TRUSTED_PROXY_COUNT", "DASHBOARD_SESSION_TTL"} <= set(reads)


def test_every_setting_the_code_reads_is_in_env_example():
    missing = {n: f for n, f in _code_reads().items() if n not in _example_names() and n not in OLD_NAMES}
    assert not missing, f"add these to .env.example: {missing}"


def test_nothing_listed_that_nothing_reads():
    stale = _example_names() - set(_code_reads()) - READ_ELSEWHERE
    assert not stale, f"not read anywhere (remove from .env.example): {stale}"
