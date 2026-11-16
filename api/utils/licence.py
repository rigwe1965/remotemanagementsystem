"""Licence check for this deployment (docs: licensing/README.md in the ProjectsDashboard repository).

A licence is one line of text, ``FKL1.<payload>.<signature>``, signed by the owner with an Ed25519 key. This module checks the
signature offline against the public key(s) built into the product, then works out what the customer may do right now.

It is a port of ``licensing/licence.mjs`` and must give the same answers: ``tests/fixtures/licence-test-vectors.json`` is the
shared contract and ``tests/test_licence.py`` replays it.

What it decides, and what it never decides
------------------------------------------
* It decides whether another **device** or **staff user** may be ADDED. A new agent registering, a device added by hand and a
  new staff account are checked. Nothing else is: a device that is already registered always reaches the server again, a
  signed-in person is never signed out, no data is locked and no feature is switched off. Over the limit, or with a lapsed or
  missing licence, the product only declines to add more, and says so in plain words.
* It does nothing at all unless ``LICENCE_ENFORCEMENT=1``. Existing deployments (including the hosted demo) therefore behave
  exactly as before until a deployment is sold with a licence.

Settings (environment)
----------------------
``LICENCE_ENFORCEMENT``   ``1`` turns the check on. Anything else: off.
``LICENCE_KEY``           the licence text. Or...
``LICENCE_FILE``          ...the path of a file containing it (re-read when the file changes, so a renewal needs no restart).
``LICENCE_PUBLIC_KEYS``   extra public keys, comma separated (the owner's key goes in ``BUILT_IN_PUBLIC_KEYS`` below).

The licence is entitlement, not copy protection: whoever runs the product controls its machine. Contract, support and updates
are what make paying worthwhile.
"""
import base64
import json
import logging
import math
import os
import re
from datetime import datetime, timedelta, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from flask import jsonify

log = logging.getLogger(__name__)

FORMAT = "FKL1"
PRODUCT = "rmm"
GRACE_DAYS = 30
EXPIRY_WARNING_DAYS = 30

# The owner's public key, printed by ``node licensing/cli.mjs keygen`` (made 2026-11-16). It can only CHECK licences, never make
# them, so it is safe to publish. A second key can be added to this tuple later to rotate keys without breaking licences already
# issued; never remove the first one while licences signed by it are still in use.
BUILT_IN_PUBLIC_KEYS: tuple = ("YgAlykUDmOaANaYUOgaOA4-2bFR8gTf-Y8mkPwTqRzU",)

_STAFF_ROLES = ("admin", "technician", "viewer")  # counted against the user limit; client portal users and the superadmin are not

# ── Reading and checking a licence ─────────────────────────────────────────────────────────────────────────────────────────


def _b64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _parse_date(s) -> datetime:
    """ISO date or date-time to an aware UTC datetime. Raises ValueError when it is neither."""
    if not isinstance(s, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}(T[\d:.]+Z)?", s):
        raise ValueError("not an ISO date")
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def check_payload(p) -> dict:
    """Raises ValueError with a plain reason when a licence payload is not acceptable (same rules as licence.mjs)."""
    if not isinstance(p, dict):
        raise ValueError("it is not an object")
    if p.get("v") != 1 or isinstance(p.get("v"), bool):
        raise ValueError("unsupported version")
    for k in ("id", "product", "customer", "tier"):
        if not isinstance(p.get(k), str) or not p[k].strip():
            raise ValueError(f"{k} is missing")
    if not re.fullmatch(r"[a-z0-9-]{2,40}", p["product"]):
        raise ValueError("product must be lower-case letters, digits and hyphens")
    iat, exp = _parse_date(p.get("iat")), _parse_date(p.get("exp"))
    if exp <= iat:
        raise ValueError("the end date must be after the start date")
    limits = p.get("limits")
    if not isinstance(limits, dict):
        raise ValueError("limits are missing")
    for k, v in limits.items():
        if not re.fullmatch(r"[a-z]{2,20}", k):
            raise ValueError(f'limit name "{k}" is not allowed')
        if v is not None and not (isinstance(v, int) and not isinstance(v, bool) and v >= 0):
            raise ValueError(f'limit "{k}" must be a whole number, or null for unlimited')
    return p


def verify(token, public_keys, product=None) -> dict:
    """Is this licence genuine? Returns ``{"ok": True, "licence": {...}}`` or ``{"ok": False, "reason": ...}``.

    reason is malformed | unsupported | bad_signature | wrong_product. Dates are not looked at (see ``evaluate``), so an expired
    licence still verifies and the product can say so kindly.
    """
    parts = token.strip().split(".") if isinstance(token, str) else []
    if len(parts) != 3:
        return {"ok": False, "reason": "malformed"}
    if parts[0] != FORMAT:
        return {"ok": False, "reason": "unsupported" if parts[0].startswith("FKL") else "malformed"}
    try:
        payload = json.loads(_b64u(parts[1]).decode("utf-8"))
        signature = _b64u(parts[2])
        check_payload(payload)
    except (ValueError, UnicodeDecodeError):  # json.JSONDecodeError and binascii.Error are ValueErrors
        return {"ok": False, "reason": "malformed"}
    body = f"{parts[0]}.{parts[1]}".encode()
    signed_by_us = False
    for raw in public_keys or ():
        try:
            Ed25519PublicKey.from_public_bytes(_b64u(raw)).verify(signature, body)
            signed_by_us = True
            break
        except (InvalidSignature, ValueError):
            continue
    if not signed_by_us:
        return {"ok": False, "reason": "bad_signature"}
    if product and payload["product"] != product:
        return {"ok": False, "reason": "wrong_product"}
    return {"ok": True, "licence": payload}


def _date_only(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%d")


def evaluate(licence: dict, now: datetime, usage: dict = None) -> dict:
    """What a verified licence entitles the customer to at ``now``, given ``usage`` (e.g. ``{"devices": 31}``).

    state: active | expiring (ends within 30 days) | grace (ended up to 30 days ago) | lapsed (ended more than 30 days ago).
    canAdd: per limit name, may another be added. banner: plain words for the admin, or None.
    """
    usage = usage or {}
    end = _parse_date(licence["exp"])
    grace_end = end + timedelta(days=GRACE_DAYS)
    days_left = math.ceil((end - now).total_seconds() / 86400)
    if now < end - timedelta(days=EXPIRY_WARNING_DAYS):
        state = "active"
    elif now < end:
        state = "expiring"
    elif now < grace_end:
        state = "grace"
    else:
        state = "lapsed"
    can_add, over = {}, {}
    for name, limit in licence["limits"].items():
        used = usage.get(name, 0)
        can_add[name] = state != "lapsed" and (limit is None or used < limit)
        if limit is not None and used > limit:
            over[name] = {"used": used, "limit": limit}
    notes = []
    if state == "expiring":
        notes.append(f"Your licence ends on {_date_only(end)}. Renew it to keep adding more.")
    if state == "grace":
        notes.append(
            f"Your licence ended on {_date_only(end)}. You can keep adding until {_date_only(grace_end)}; "
            "renew it to continue after that."
        )
    if state == "lapsed":
        notes.append(
            f"Your licence ended on {_date_only(end)}. Everything you have keeps working, "
            "but you cannot add more until it is renewed."
        )
    for name, o in over.items():
        notes.append(f"You are using {o['used']} {name}; your licence covers {o['limit']}.")
    return {
        "state": state,
        "daysLeft": days_left,
        "endsOn": _date_only(end),
        "graceEndsOn": _date_only(grace_end),
        "limits": licence["limits"],
        "usage": usage,
        "canAdd": can_add,
        "over": over,
        "banner": " ".join(notes) if notes else None,
    }


# ── This deployment ────────────────────────────────────────────────────────────────────────────────────────────────────────


def enforcement_on() -> bool:
    return os.getenv("LICENCE_ENFORCEMENT", "").strip() == "1"


def public_keys() -> list:
    extra = [k.strip() for k in os.getenv("LICENCE_PUBLIC_KEYS", "").split(",") if k.strip()]
    return [*BUILT_IN_PUBLIC_KEYS, *extra]


_file_cache = {"path": None, "mtime": None, "text": None}


def licence_text() -> str:
    """The licence text from LICENCE_KEY, or from LICENCE_FILE (re-read only when the file changes). Empty when there is none."""
    inline = os.getenv("LICENCE_KEY", "").strip()
    if inline:
        return inline
    path = os.getenv("LICENCE_FILE", "").strip()
    if not path:
        return ""
    try:
        mtime = os.path.getmtime(path)
        if _file_cache["path"] != path or _file_cache["mtime"] != mtime:
            with open(path, encoding="utf-8") as f:
                _file_cache.update(path=path, mtime=mtime, text=f.read().strip())
        return _file_cache["text"] or ""
    except OSError:
        log.warning("LICENCE_FILE %s cannot be read", path)
        return ""


def current() -> dict:
    """The licence this deployment has: ``{"found", "ok", "reason", "licence"}``. Never raises."""
    text = licence_text()
    if not text:
        return {"found": False, "ok": False, "reason": "none", "licence": None}
    v = verify(text, public_keys(), PRODUCT)
    return {"found": True, "ok": v["ok"], "reason": v.get("reason"), "licence": v.get("licence")}


def usage_now() -> dict:
    """What is in use now: every device (agent or added by hand) and every active staff account."""
    from extensions import db
    from models.device import Device
    from models.user import User

    devices = db.session.query(db.func.count(Device.id)).scalar() or 0
    users = (
        db.session.query(db.func.count(User.id)).filter(User.is_active.is_(True), User.role.in_(_STAFF_ROLES)).scalar() or 0
    )
    return {"devices": devices, "users": users}


_NO_LICENCE = (
    "No valid licence was found, so new devices and staff accounts cannot be added. "
    "Everything already set up keeps working. Install the licence you were sent."
)


def status(now: datetime = None) -> dict:
    """Everything the admin screen needs. Never contains the licence text or signature."""
    now = now or datetime.now(timezone.utc)
    if not enforcement_on():
        return {"enforced": False, "state": "not_enforced", "banner": None}
    cur = current()
    if not cur["ok"]:
        return {"enforced": True, "state": "unlicensed", "reason": cur["reason"], "banner": _NO_LICENCE}
    lic = cur["licence"]
    e = evaluate(lic, now, usage_now())
    return {"enforced": True, "customer": lic["customer"], "tier": lic["tier"], **e}


def check_can_add(kind: str, now: datetime = None):
    """Call before ADDING a ``"devices"`` or ``"users"`` entry. Returns None when it may go ahead, else ``(response, 402)``."""
    if not enforcement_on():
        return None
    now = now or datetime.now(timezone.utc)
    cur = current()
    if not cur["ok"]:
        return jsonify({"error": _NO_LICENCE, "code": "LICENCE_REQUIRED"}), 402
    e = evaluate(cur["licence"], now, usage_now())
    if e["state"] == "lapsed":
        return jsonify({"error": e["banner"], "code": "LICENCE_LAPSED"}), 402
    if kind in e["canAdd"] and not e["canAdd"][kind]:
        limit = e["limits"][kind]
        return (
            jsonify({"error": f"Your licence covers {limit} {kind} and all of them are in use. Renew or upgrade to add more.", "code": "LICENCE_LIMIT"}),
            402,
        )
    return None
