"""
System metrics and hardware info collector.
Cross-platform: Windows / macOS / Linux.
Uses psutil for shared metrics; OS-specific branches for patches and software.
"""
import locale
import platform
import socket
import subprocess
import sys
import time
import uuid as uuid_lib
import logging
from pathlib import Path

import psutil

logger = logging.getLogger(__name__)

_PLATFORM = sys.platform  # "win32" | "darwin" | "linux"
_CREATE_NO_WINDOW = 0x08000000 if _PLATFORM == "win32" else 0


# ── Output decoding ────────────────────────────────────────────────────────────

def _decode_output(raw: bytes) -> str:
    """Decode subprocess bytes, handling PowerShell's UTF-16 LE output."""
    if raw.startswith(b"\xff\xfe"):
        return raw.decode("utf-16-le").lstrip("﻿")
    if raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16-be").lstrip("﻿")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        enc = locale.getpreferredencoding(False) or "cp1252"
        return raw.decode(enc, errors="replace")


def _is_winget_progress_line(line: str) -> bool:
    return any(
        '─' <= c <= '▟'
        or '■' <= c <= '◿'
        or c == '�'
        for c in line
    )


def _run(cmd: list, timeout: int = 30, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        timeout=timeout,
        creationflags=_CREATE_NO_WINDOW,
        **kwargs,
    )


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _get_primary_mac() -> str:
    try:
        mac = hex(uuid_lib.getnode())[2:].upper().zfill(12)
        return ":".join(mac[i:i+2] for i in range(0, 12, 2))
    except Exception:
        return "00:00:00:00:00:00"


def _get_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _get_primary_disk() -> dict:
    root = "C:\\" if _PLATFORM == "win32" else "/"
    try:
        usage = psutil.disk_usage(root)
        return {
            "percent": round(usage.percent, 1),
            "used_gb": round(usage.used / (1024 ** 3), 2),
            "total_gb": round(usage.total / (1024 ** 3), 2),
        }
    except Exception:
        return {}


def _get_all_disks() -> list:
    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "total_gb": round(usage.total / (1024 ** 3), 2),
                "used_gb": round(usage.used / (1024 ** 3), 2),
                "free_gb": round(usage.free / (1024 ** 3), 2),
                "percent": round(usage.percent, 1),
            })
        except Exception:
            continue
    return disks


def _get_battery() -> dict:
    try:
        batt = psutil.sensors_battery()
        if batt:
            return {
                "battery_pct": round(batt.percent, 1),
                "battery_plugged": batt.power_plugged,
            }
    except Exception:
        pass
    return {"battery_pct": None, "battery_plugged": None}


def _get_top_processes(n=5) -> list:
    try:
        procs = []
        deadline = time.monotonic() + 3.0
        max_scan = 200
        scanned = 0
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            if time.monotonic() > deadline or scanned >= max_scan:
                break
            scanned += 1
            try:
                info = proc.info
                procs.append({
                    "pid": info["pid"],
                    "name": info["name"],
                    "cpu_pct": round(info["cpu_percent"] or 0, 1),
                    "mem_pct": round(info["memory_percent"] or 0, 1),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return sorted(procs, key=lambda x: x["cpu_pct"], reverse=True)[:n]
    except Exception:
        return []


# ── Hardware info ──────────────────────────────────────────────────────────────

def get_hardware_info() -> dict:
    """Collect static hardware/OS info for device registration."""
    os_map = {"win32": "windows", "darwin": "mac", "linux": "linux"}
    info = {
        "hostname": socket.gethostname(),
        "platform": os_map.get(_PLATFORM, _PLATFORM),
        "os_name": platform.system(),
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "cpu_cores": psutil.cpu_count(logical=True),
        "ram_gb": round(psutil.virtual_memory().total / (1024 ** 3), 2),
        "mac_address": _get_primary_mac(),
        "ip_address": _get_local_ip(),
        "agent_version": "1.0.0",
        "cpu_model": platform.processor() or None,
    }

    if _PLATFORM == "win32":
        _enrich_windows(info)
    elif _PLATFORM == "darwin":
        _enrich_macos(info)
    elif _PLATFORM == "linux":
        _enrich_linux(info)

    return info


def _enrich_windows(info: dict) -> None:
    try:
        import wmi
        c = wmi.WMI()
        cpus = c.Win32_Processor()
        if cpus:
            info["cpu_model"] = cpus[0].Name.strip()
        bios = c.Win32_BIOS()
        if bios:
            info["serial_number"] = bios[0].SerialNumber.strip()
        os_info = c.Win32_OperatingSystem()
        if os_info:
            info["os_build"] = os_info[0].BuildNumber
            info["os_name"] = os_info[0].Caption.strip()
            info["os_version"] = os_info[0].Version
    except Exception as e:
        logger.warning("WMI collection failed (non-fatal): %s", e)


def _enrich_macos(info: dict) -> None:
    try:
        r = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
        if r.returncode == 0:
            info["cpu_model"] = r.stdout.decode("utf-8", errors="replace").strip()
    except Exception:
        pass
    try:
        r = _run(["system_profiler", "SPHardwareDataType"])
        for line in r.stdout.decode("utf-8", errors="replace").splitlines():
            if "Serial Number" in line:
                info["serial_number"] = line.split(":")[-1].strip()
                break
        for line in r.stdout.decode("utf-8", errors="replace").splitlines():
            if "Model Name" in line:
                info["os_name"] = line.split(":")[-1].strip()
                break
    except Exception:
        pass
    info["os_version"] = platform.mac_ver()[0] or platform.version()


def _enrich_linux(info: dict) -> None:
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
        for line in cpuinfo.splitlines():
            if line.startswith("model name"):
                info["cpu_model"] = line.split(":", 1)[-1].strip()
                break
    except Exception:
        pass
    try:
        r = _run(["dmidecode", "-s", "system-serial-number"], timeout=5)
        if r.returncode == 0:
            serial = r.stdout.decode("utf-8", errors="replace").strip()
            if serial and serial.lower() not in ("", "none", "not specified"):
                info["serial_number"] = serial
    except Exception:
        pass
    try:
        os_release = Path("/etc/os-release").read_text(encoding="utf-8", errors="replace")
        for line in os_release.splitlines():
            if line.startswith("PRETTY_NAME="):
                info["os_name"] = line.split("=", 1)[-1].strip().strip('"')
                break
    except Exception:
        pass


# ── Live metrics ───────────────────────────────────────────────────────────────

def get_metrics() -> dict:
    """Collect current system metrics for heartbeat payload."""
    cpu_pct = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    boot_time = psutil.boot_time()
    uptime = time.time() - boot_time
    primary_disk = _get_primary_disk()
    net = psutil.net_io_counters()
    disks = _get_all_disks()
    battery = _get_battery()
    top_procs = _get_top_processes()

    return {
        "cpu_pct": round(cpu_pct, 1),
        "ram_pct": round(mem.percent, 1),
        "ram_used_gb": round(mem.used / (1024 ** 3), 2),
        "disk_pct": primary_disk.get("percent", 0),
        "disk_used_gb": primary_disk.get("used_gb", 0),
        "disk_total_gb": primary_disk.get("total_gb", 0),
        "network_bytes_sent": net.bytes_sent,
        "network_bytes_recv": net.bytes_recv,
        "uptime_seconds": int(uptime),
        "disks": disks,
        "top_processes": top_procs,
        "cpu_model": platform.processor() or None,
        **battery,
    }


# ── Pending patches ────────────────────────────────────────────────────────────

def get_pending_patches() -> list:
    """Return list of pending patches for the current OS."""
    if _PLATFORM == "win32":
        return _patches_windows()
    if _PLATFORM == "darwin":
        return _patches_macos()
    return _patches_linux()


def _patches_windows() -> list:
    import json
    script = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
        "$OutputEncoding = [System.Text.Encoding]::UTF8\n"
        "$ErrorActionPreference='SilentlyContinue'\n"
        "try {\n"
        "    $sess = New-Object -ComObject Microsoft.Update.Session\n"
        "    $srch = $sess.CreateUpdateSearcher()\n"
        "    $res = $srch.Search(\"IsInstalled=0 and Type='Software'\")\n"
        "    $out = @()\n"
        "    foreach ($u in $res.Updates) {\n"
        "        $kb = if ($u.KBArticleIDs.Count -gt 0) { \"KB\" + $u.KBArticleIDs[0] } else { $null }\n"
        "        $sev = $u.MsrcSeverity\n"
        "        $type = if ($sev -eq 'Critical') { 'critical' } elseif ($sev -eq 'Important') { 'security' } else { 'feature' }\n"
        "        $out += @{ name=$u.Title; kb_id=$kb; patch_type=$type }\n"
        "    }\n"
        "    $out | ConvertTo-Json -Compress\n"
        "} catch { '[]' }\n"
    )
    try:
        result = _run(["powershell", "-NonInteractive", "-NoProfile", "-Command", script], timeout=60)
        raw = _decode_output(result.stdout).strip()
        if not raw:
            return []
        data = __import__("json").loads(raw)
        if isinstance(data, dict):
            data = [data]
        return data[:500]
    except Exception as e:
        logger.warning("_patches_windows failed: %s", e)
        return []


def _patches_macos() -> list:
    patches = []

    # macOS built-in software updates
    try:
        r = _run(["softwareupdate", "-l"], timeout=60)
        out = r.stdout.decode("utf-8", errors="replace") + r.stderr.decode("utf-8", errors="replace")
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("*") or line.startswith("-"):
                name = line.lstrip("*- ").strip()
                if name:
                    patches.append({"name": name, "patch_type": "feature", "source": "softwareupdate"})
    except Exception as e:
        logger.warning("softwareupdate check failed: %s", e)

    # Homebrew outdated packages
    try:
        r = _run(["brew", "outdated", "--json=v2"], timeout=30)
        if r.returncode == 0:
            import json
            data = json.loads(r.stdout.decode("utf-8", errors="replace"))
            for pkg in data.get("formulae", []):
                patches.append({
                    "name": pkg.get("name", ""),
                    "version": pkg.get("installed_versions", ["?"])[-1],
                    "available_version": pkg.get("current_version", ""),
                    "patch_type": "feature",
                    "source": "brew",
                })
            for pkg in data.get("casks", []):
                patches.append({
                    "name": pkg.get("name", ""),
                    "patch_type": "feature",
                    "source": "brew-cask",
                })
    except FileNotFoundError:
        pass  # brew not installed — normal
    except Exception as e:
        logger.debug("brew outdated failed: %s", e)

    return patches[:500]


def _detect_linux_pkg_manager() -> str:
    """Return 'apt' | 'dnf' | 'yum' | 'pacman' | 'unknown'."""
    for mgr in ("apt-get", "dnf", "yum", "pacman"):
        try:
            r = _run(["which", mgr], timeout=3)
            if r.returncode == 0:
                return mgr.replace("-get", "") if mgr == "apt-get" else mgr
        except Exception:
            pass
    return "unknown"


def _patches_linux() -> list:
    mgr = _detect_linux_pkg_manager()
    patches = []

    try:
        if mgr == "apt":
            r = _run(["apt-get", "-s", "upgrade"], timeout=60)
            for line in r.stdout.decode("utf-8", errors="replace").splitlines():
                if line.startswith("Inst "):
                    parts = line.split()
                    name = parts[1] if len(parts) > 1 else line
                    version = parts[2].strip("[]()") if len(parts) > 2 else ""
                    patches.append({"name": name, "version": version, "patch_type": "feature", "source": "apt"})

        elif mgr in ("dnf", "yum"):
            r = _run([mgr, "check-update", "-q"], timeout=60)
            for line in r.stdout.decode("utf-8", errors="replace").splitlines():
                parts = line.split()
                if len(parts) >= 2 and not line.startswith(" ") and "." in parts[0]:
                    patches.append({"name": parts[0], "version": parts[1], "patch_type": "feature", "source": mgr})

        elif mgr == "pacman":
            r = _run(["pacman", "-Qu"], timeout=30)
            for line in r.stdout.decode("utf-8", errors="replace").splitlines():
                parts = line.split()
                if len(parts) >= 4:
                    patches.append({
                        "name": parts[0],
                        "version": parts[1],
                        "available_version": parts[3],
                        "patch_type": "feature",
                        "source": "pacman",
                    })
    except Exception as e:
        logger.warning("_patches_linux(%s) failed: %s", mgr, e)

    return patches[:500]


# ── Installed software ─────────────────────────────────────────────────────────

def get_installed_software() -> list:
    """Get installed software list for the current OS."""
    if _PLATFORM == "win32":
        return _software_windows()
    if _PLATFORM == "darwin":
        return _software_macos()
    return _software_linux()


def _software_windows() -> list:
    software = []
    try:
        software.extend(_get_registry_software())
    except Exception as e:
        logger.warning("Registry software collection failed: %s", e)
    try:
        software.extend(_get_winget_software())
    except Exception as e:
        logger.debug("Winget not available: %s", e)
    seen, unique = set(), []
    for item in software:
        key = item["name"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _software_macos() -> list:
    software = []

    # Applications from /Applications directory (no external tool needed)
    try:
        import plistlib
        for app_path in Path("/Applications").glob("*.app"):
            plist_path = app_path / "Contents" / "Info.plist"
            if plist_path.exists():
                try:
                    with open(plist_path, "rb") as f:
                        plist = plistlib.load(f)
                    name = plist.get("CFBundleName") or app_path.stem
                    version = plist.get("CFBundleShortVersionString") or plist.get("CFBundleVersion")
                    software.append({"name": name, "version": version, "source": "applications"})
                except Exception:
                    software.append({"name": app_path.stem, "version": None, "source": "applications"})
    except Exception as e:
        logger.warning("macOS /Applications scan failed: %s", e)

    # Homebrew formula list
    try:
        r = _run(["brew", "list", "--versions", "--formula"], timeout=30)
        if r.returncode == 0:
            for line in r.stdout.decode("utf-8", errors="replace").splitlines():
                parts = line.strip().split()
                if parts:
                    software.append({
                        "name": parts[0],
                        "version": parts[1] if len(parts) > 1 else None,
                        "source": "brew",
                    })
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.debug("brew list failed: %s", e)

    seen, unique = set(), []
    for item in software:
        key = item["name"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _software_linux() -> list:
    mgr = _detect_linux_pkg_manager()
    software = []

    try:
        if mgr == "apt":
            r = _run(
                ["dpkg-query", "-W", "-f=${Package}\t${Version}\t${Maintainer}\t${db:Status-Abbrev}\n"],
                timeout=30,
            )
            for line in r.stdout.decode("utf-8", errors="replace").splitlines():
                parts = line.split("\t")
                if len(parts) >= 4 and parts[3].strip().startswith("i"):
                    software.append({
                        "name": parts[0].strip(),
                        "version": parts[1].strip(),
                        "publisher": parts[2].strip(),
                        "source": "dpkg",
                    })

        elif mgr in ("dnf", "yum"):
            r = _run(["rpm", "-qa", "--queryformat", "%{NAME}\t%{VERSION}-%{RELEASE}\t%{VENDOR}\n"], timeout=30)
            for line in r.stdout.decode("utf-8", errors="replace").splitlines():
                parts = line.split("\t")
                if len(parts) >= 2:
                    software.append({
                        "name": parts[0].strip(),
                        "version": parts[1].strip(),
                        "publisher": parts[2].strip() if len(parts) > 2 else None,
                        "source": "rpm",
                    })

        elif mgr == "pacman":
            r = _run(["pacman", "-Q"], timeout=30)
            for line in r.stdout.decode("utf-8", errors="replace").splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    software.append({"name": parts[0], "version": parts[1], "source": "pacman"})

    except Exception as e:
        logger.warning("_software_linux(%s) failed: %s", mgr, e)

    return software


# ── Windows-only helpers ───────────────────────────────────────────────────────

def _get_registry_software() -> list:
    import winreg
    software = []
    deadline = time.monotonic() + 20.0
    keys = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, key_path in keys:
        if time.monotonic() > deadline:
            logger.warning("Registry enumeration deadline reached — results may be partial")
            break
        try:
            with winreg.OpenKey(hive, key_path) as key:
                for i in range(winreg.QueryInfoKey(key)[0]):
                    if time.monotonic() > deadline:
                        break
                    try:
                        subkey_name = winreg.EnumKey(key, i)
                        with winreg.OpenKey(key, subkey_name) as subkey:
                            name = _reg_val(subkey, "DisplayName")
                            if not name:
                                continue
                            software.append({
                                "name": name,
                                "version": _reg_val(subkey, "DisplayVersion"),
                                "publisher": _reg_val(subkey, "Publisher"),
                                "install_date": _reg_val(subkey, "InstallDate"),
                                "source": "registry",
                            })
                    except Exception:
                        continue
        except Exception:
            continue
    return software


def _reg_val(key, name: str):
    try:
        import winreg
        val, _ = winreg.QueryValueEx(key, name)
        return str(val).strip() if val else None
    except Exception:
        return None


def _get_winget_software() -> list:
    result = _run(["winget", "list", "--accept-source-agreements"], timeout=30)
    if result.returncode != 0:
        return []
    lines = _decode_output(result.stdout).splitlines()
    sep_idx = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if _is_winget_progress_line(stripped):
            continue
        if stripped and all(c in "-_ " for c in stripped) and len(stripped) > 10:
            sep_idx = idx
            break
    if sep_idx is None:
        return []
    software = []
    for line in lines[sep_idx + 1:]:
        if _is_winget_progress_line(line):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        name = " ".join(parts[:-3]) if len(parts) > 3 else parts[0]
        version = parts[-3] if len(parts) > 3 else parts[-1]
        if not name:
            continue
        software.append({"name": name, "version": version, "source": "winget"})
    return software
