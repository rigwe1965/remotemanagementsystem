"""
Network scan and agentless device ping-monitoring tasks.
Uses stdlib only (subprocess ping + arp, ipaddress, concurrent.futures).
No nmap or external scanning library required.
"""
import ipaddress
import logging
import re
import subprocess
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Ensure api/ is in sys.path so Flask app modules are importable from Celery worker
_api_dir = str(Path(__file__).parent.parent)
if _api_dir not in sys.path:
    sys.path.insert(0, _api_dir)

from tasks.celery_app import celery

# Windows: suppress console window for subprocesses (CLAUDE.md rule)
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

from tasks._app_singleton import get_app as _get_app

# Redis lock — prevents duplicate dispatch when more than one celery beat is
# accidentally running (same pattern as tasks/alert_tasks.py's _EVAL_LOCK_KEY).
# Needed because celery's --pidfile does NOT reliably stop a second beat on
# native Windows (its liveness check reported a genuinely-running process as
# stale in direct testing — 2026-10-01); a task-level lock is OS-agnostic and
# protects correctness even if that process-level guard fails.
_PING_LOCK_KEY = "rmm:ping_agentless:lock"
_PING_LOCK_TTL = 270  # seconds — expires just before the next 300s beat fires


# ── Low-level helpers ─────────────────────────────────────────────────────────

def _ping_host(ip: str, timeout_ms: int = 500) -> bool:
    """Return True if host responds to ICMP echo. Works on Windows and Unix."""
    if sys.platform == "win32":
        cmd = ["ping", "-n", "1", "-w", str(timeout_ms), ip]
    else:
        cmd = ["ping", "-c", "1", "-W", "1", ip]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            creationflags=CREATE_NO_WINDOW,
        )
        return result.returncode == 0
    except Exception:
        return False


def _get_mac_for_ip(ip: str) -> str | None:
    """
    Read MAC from ARP cache after a ping (cache is populated automatically).
    Windows: 'arp -a <ip>' output line looks like:
      '  192.168.1.5          aa-bb-cc-dd-ee-ff     dynamic'
    Unix: 'arp -n <ip>' output looks like:
      '192.168.1.5 ether aa:bb:cc:dd:ee:ff C eth0'
    """
    try:
        if sys.platform == "win32":
            cmd = ["arp", "-a", ip]
        else:
            cmd = ["arp", "-n", ip]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=CREATE_NO_WINDOW,
        )
        match = re.search(r"([\da-fA-F]{2}[:\-]){5}[\da-fA-F]{2}", result.stdout)
        if match:
            return match.group(0).replace("-", ":").upper()
    except Exception:
        pass
    return None


def _guess_platform(vendor: str) -> tuple[str, str]:
    """
    Returns (platform, device_type) based on OUI vendor string.
    Conservative: Apple could be Mac or iPhone; mark mobile for common ranges.
    """
    v = vendor.lower()
    if "apple" in v:
        return "ios", "mobile"
    if any(x in v for x in ("samsung", "xiaomi", "huawei", "oppo", "motorola",
                             "oneplus", "realme", "vivo", "zte", "nokia",
                             "google", "pixel")):
        return "android", "mobile"
    if any(x in v for x in ("raspberry pi",)):
        return "linux", "desktop"
    return "unknown", "unknown"


def _probe_platform(ip: str) -> tuple[str, str]:
    """
    Probe well-known ports to guess OS/platform when OUI is Unknown.
    Returns (platform, device_type). Falls back to ("unknown", "unknown").

    Port map:
      62078 → iOS  (iTunes Wi-Fi sync, open on iPhones/iPads)
      5555  → Android (ADB, enabled on developer phones)
      445   → Windows (SMB)
      139   → Windows (NetBIOS)
      22    → Linux or macOS (SSH)
      5000  → macOS (AirPlay / Control Center — skip, conflicts with our API)
      548   → macOS (AFP file sharing)
      3389  → Windows (RDP)
    """
    import socket

    def _open(port: int, timeout: float = 0.5) -> bool:
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                return True
        except Exception:
            return False

    if _open(62078):
        return "ios", "mobile"
    if _open(5555):
        return "android", "mobile"
    # Require 2+ Windows ports to avoid false-positives from routers/NAS with only SMB open.
    # Fritz!Box and similar devices expose port 445 (SMB) but not 139 or 3389.
    # Real Windows PCs have 445+139 by default; RDP (3389) optional.
    win_ports = (_open(3389), _open(445), _open(139))
    if sum(win_ports) >= 2:
        return "windows", "desktop"
    if _open(548):
        return "mac", "desktop"
    if _open(22):
        return "linux", "desktop"
    return "unknown", "unknown"


def _get_hostname(ip: str) -> str | None:
    """Reverse DNS lookup — returns hostname if resolvable (e.g. iPhone.local)."""
    import socket
    try:
        name = socket.gethostbyaddr(ip)[0]
        return name if name != ip else None
    except Exception:
        return None


# Android model-name keywords that appear in rDNS hostnames assigned by routers.
_ANDROID_HOSTNAME_KEYWORDS = (
    "android", "galaxy", "samsung", "pixel", "oneplus", "xiaomi", "redmi",
    "poco", "mi-", "huawei", "honor", "oppo", "vivo", "realme", "moto",
    "motorola", "nokia", "zte", "infinix", "tecno", "itel",
    # Samsung model numbers (Fritz!Box format: "Name-s-S21-Ultra")
    "-s10", "-s20", "-s21", "-s22", "-s23", "-s24",
    "-note10", "-note20", "-note",
    "-a12", "-a13", "-a14", "-a15", "-a16", "-a22", "-a23",
    "-a32", "-a33", "-a34", "-a35", "-a50", "-a51", "-a52", "-a53", "-a54",
    "-a55", "-a72", "-a73",
    "-fold", "-flip", "-ultra",
)

# iOS/macOS hostname keywords
_IOS_HOSTNAME_KEYWORDS = ("iphone", "ipad", "ipod")


def _guess_platform_from_hostname(hostname: str) -> tuple[str, str]:
    """
    Infer platform from rDNS hostname when OUI lookup + port probe both fail.
    Routers (Fritz!Box, ASUS, TP-Link) often assign the device's advertised name.
    Returns (platform, device_type) or ("unknown", "unknown").
    """
    if not hostname:
        return "unknown", "unknown"
    h = hostname.lower()
    if any(k in h for k in _IOS_HOSTNAME_KEYWORDS):
        return "ios", "mobile"
    if any(k in h for k in _ANDROID_HOSTNAME_KEYWORDS):
        return "android", "mobile"
    return "unknown", "unknown"


def _upsert_agentless_host(ip: str, mac: str | None, vendor: str,
                           platform: str, device_type: str,
                           customer_id: str | None = None,
                           hostname: str | None = None) -> str:
    """
    Persist a discovered host as an agentless Device.
    Returns 'created' or 'updated'.
    Imported inside tasks/routes that run within Flask app context.
    """
    from extensions import db
    from models.device import Device

    now = datetime.now(timezone.utc)
    existing = None

    # Primary key: MAC address (stable across IP changes)
    if mac:
        existing = Device.query.filter_by(mac_address=mac).first()

    # Fallback: match by IP — search ALL devices so agent-managed machines aren't duplicated
    if not existing:
        existing = Device.query.filter_by(ip_address=ip).first()

    # Fallback: match by hostname (bare part, case-insensitive) — catches multi-adapter machines
    # where agent registered with Ethernet MAC/IP but scan sees WiFi MAC/IP.
    # e.g. agent hostname "DESKTOP-0NSDM8E", scan rdns "DESKTOP-0NSDM8E.fritz.box" → same bare name.
    if not existing and hostname:
        bare_rdns = hostname.split(".")[0].upper()
        existing = Device.query.filter(
            Device.hostname.ilike(bare_rdns)
        ).first()
        if existing is None:
            # Also try matching agent devices whose stored hostname starts with bare_rdns
            existing = Device.query.filter(
                Device.hostname.ilike(f"{bare_rdns}.%")
            ).first()

    if existing:
        # Never demote an agent-managed device
        if not existing.is_agentless:
            return "skipped"
        existing.ip_address = ip
        existing.last_seen = now
        existing.is_online = True
        existing.status = "healthy"
        if vendor and vendor != "Unknown":
            existing.vendor = vendor
        # Upgrade platform/device_type if we now have better detection
        if platform != "unknown" and existing.platform in (None, "unknown"):
            existing.platform = platform
            existing.device_type = device_type
        db.session.commit()
        return "updated"

    # Create new agentless device
    device = Device(
        hostname=hostname or ip,   # use rDNS name if available, else IP
        platform=platform,
        device_type=device_type,
        ip_address=ip,
        mac_address=mac,
        vendor=vendor,
        is_agentless=True,
        is_online=True,
        status="healthy",
        last_seen=now,
        customer_id=customer_id,
    )
    db.session.add(device)
    db.session.commit()
    return "created"


# ── Core scan logic (called from Flask thread, runs inside app_context) ────────

def _run_scan(scan_id: str):
    """Pure scan logic — no Celery, no app context. Called from background thread."""
    import time as _time
    from extensions import db
    from models.audit import NetworkScan
    from utils.oui import lookup_vendor
    from utils.usage_tracker import record_event

    _t0 = _time.perf_counter()
    scan = db.session.get(NetworkScan, scan_id)
    if not scan:
        return

    try:
        net = ipaddress.ip_network(scan.scan_range, strict=False)
    except ValueError as e:
        scan.status = "failed"
        scan.completed_at = datetime.now(timezone.utc)
        scan.discovered_hosts = [{"error": f"Invalid CIDR range: {e}"}]
        db.session.commit()
        return

    hosts_iter = list(net.hosts())
    if len(hosts_iter) > 254:
        scan.status = "failed"
        scan.completed_at = datetime.now(timezone.utc)
        scan.discovered_hosts = [{"error": "Range too large — use /24 or smaller"}]
        db.session.commit()
        return

    discovered = []
    created_count = 0

    try:
        with ThreadPoolExecutor(max_workers=50) as pool:
            futures = {pool.submit(_ping_host, str(ip)): str(ip) for ip in hosts_iter}
            for future in as_completed(futures):
                ip = futures[future]
                try:
                    alive = future.result()
                except Exception:
                    alive = False

                if not alive:
                    continue

                mac = _get_mac_for_ip(ip)
                vendor = lookup_vendor(mac) if mac else "Unknown"
                platform, device_type = _guess_platform(vendor)

                # Try reverse DNS for a friendly hostname (needed before hostname-based detection)
                rdns = _get_hostname(ip)

                # If OUI lookup failed, try port probing — skip for actual router/gateway hostnames.
                # Match only bare router names, not device.fritz.box suffixes (all LAN devices get those).
                _ROUTER_EXACT = ("fritz.box", "fritzbox", "router", "gateway", "modem",
                                 "router.fritz.box", "dsldevice", "repeater", "ap.lan")
                h_lower = (rdns or "").lower()
                # Bare hostname (strip .fritz.box / .local suffix for comparison)
                bare = h_lower.split(".")[0]
                is_router = h_lower in _ROUTER_EXACT or bare in ("router", "gateway", "modem",
                                                                  "fritzbox", "repeater")
                if platform == "unknown" and not is_router:
                    platform, device_type = _probe_platform(ip)

                # Final fallback: infer from rDNS hostname (catches Android phones with ADB off)
                if platform == "unknown" and rdns:
                    platform, device_type = _guess_platform_from_hostname(rdns)

                discovered.append({
                    "ip": ip,
                    "mac": mac,
                    "vendor": vendor,
                    "platform": platform,
                    "device_type": device_type,
                    "hostname": rdns or ip,
                    "status": "up",
                })

                # Skip persisting router/gateway devices — no value in tracking them as endpoints
                if is_router:
                    continue

                result = _upsert_agentless_host(
                    ip=ip, mac=mac, vendor=vendor,
                    platform=platform, device_type=device_type,
                    customer_id=scan.customer_id,
                    hostname=rdns,
                )
                if result == "created":
                    created_count += 1

        scan.status = "completed"
        scan.completed_at = datetime.now(timezone.utc)
        scan.discovered_hosts = discovered
        scan.new_devices_count = created_count
        db.session.commit()
        record_event(service="network_scan", feature=f"cidr_scan:{len(hosts_iter)}_hosts", status="success",
                     latency_ms=int((_time.perf_counter() - _t0) * 1000))
    except Exception as exc:
        # Without this, an exception here (e.g. a DB error in _upsert_agentless_host, or a
        # connection drop mid-scan) left `scan` stuck at status="running" forever — the
        # Network Discovery dashboard page polls this row and would show an indefinite
        # spinner with no error surfaced.
        db.session.rollback()
        scan.status = "failed"
        scan.completed_at = datetime.now(timezone.utc)
        scan.discovered_hosts = [{"error": str(exc)[:300]}]
        db.session.commit()
        logger.exception("Network scan %s failed", scan_id)
        record_event(service="network_scan", feature=f"cidr_scan:{len(hosts_iter)}_hosts", status="error",
                     latency_ms=int((_time.perf_counter() - _t0) * 1000), error=type(exc).__name__)


# ── Celery tasks (kept for beat schedule / future use) ─────────────────────────

@celery.task(name="tasks.network_tasks.run_network_scan", bind=True, max_retries=2)
def run_network_scan(self, scan_id: str):
    """Celery wrapper — delegates to _run_scan inside a Flask app context."""
    with _get_app().app_context():
        _run_scan(scan_id)


@celery.task(name="tasks.network_tasks.ping_agentless_devices", bind=True)
def ping_agentless_devices(self):
    """
    Ping all known agentless devices and update online/offline status.
    Runs every 5 minutes via Celery beat.
    """
    import time as _time
    from extensions import db
    from models.device import Device
    from utils.usage_tracker import record_event
    from utils.cache import _get_client as _get_redis

    try:
        _r = _get_redis()
        acquired = _r.set(_PING_LOCK_KEY, "1", nx=True, ex=_PING_LOCK_TTL)
        if not acquired:
            logger.info("ping_agentless_devices: skipping — previous run still in progress")
            return
    except Exception as exc:
        logger.warning("ping_agentless_devices: could not acquire lock (%s) — running without it", exc)
        _r = None

    _t0 = _time.perf_counter()
    try:
        with _get_app().app_context():
            now = datetime.now(timezone.utc)
            devices = Device.query.filter_by(is_agentless=True).filter(
                Device.ip_address.isnot(None)
            ).all()

            def _check(device):
                return device.ip_address, _ping_host(device.ip_address)

            ip_to_device = {d.ip_address: d for d in devices}
            with ThreadPoolExecutor(max_workers=min(50, len(devices) or 1)) as pool:
                for ip, alive in pool.map(_check, devices):
                    device = ip_to_device[ip]
                    if alive:
                        device.is_online = True
                        device.status = "healthy"
                        device.last_seen = now
                    else:
                        if device.last_seen:
                            age_seconds = (now - device.last_seen.replace(tzinfo=timezone.utc)
                                           if device.last_seen.tzinfo is None
                                           else (now - device.last_seen)).total_seconds()
                            if age_seconds > 600:
                                device.is_online = False
                                device.status = "offline"
                        else:
                            device.is_online = False

            db.session.commit()
            record_event(service="network_scan", feature=f"agentless_ping:{len(devices)}_devices", status="success",
                         latency_ms=int((_time.perf_counter() - _t0) * 1000))
    finally:
        if _r is not None:
            try:
                _r.delete(_PING_LOCK_KEY)
            except Exception:
                pass
