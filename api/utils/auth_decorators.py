"""Shared role-authorization helpers for API routes.

Centralizes the `_require_role(*roles)` guard that was previously copy-pasted
identically across 14 route files (devices.py, alerts.py, billing.py,
automation.py, customers.py, network.py, patches.py, psa.py, scripts.py,
sensors.py, sla_policies.py, terminal.py, tickets.py, mobile_mdm.py) — one
function to audit/patch instead of 14 drifting copies. `org_settings.py` and
`usage.py` also call `require_role("admin")` directly (2026-10 dup-code pass)
— `admin.py`'s own `_require_admin()` stays separate since it additionally
loads the `User` row from a fresh DB read for its callers, not just a
pass/fail check.
"""
from functools import wraps

from flask import jsonify
from flask_jwt_extended import get_jwt


def require_role(*roles):
    """Returns a (body, status) 403 tuple if the caller's JWT role is not one of
    `roles`, else None. Superadmin always bypasses. Call at the top of a view
    function: `err = require_role("admin"); if err: return err`."""
    claims = get_jwt()
    if claims.get("role") == "superadmin":
        return None  # superadmin bypasses all role checks
    if claims.get("role") not in roles:
        return jsonify({"error": "Insufficient permissions"}), 403
    return None


def roles_required(*roles, allow_superadmin=True):
    """Decorator form of require_role(), for view functions that only need a
    single, static role check at entry (must be stacked under @jwt_required()).
    Not a drop-in replacement everywhere: some routes call require_role()
    conditionally mid-function with a dynamically computed role list (e.g.
    mobile_mdm.py's per-command role_allowed) — those keep calling
    require_role() directly instead of using this decorator."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            claims = get_jwt()
            role = claims.get("role")
            if allow_superadmin and role == "superadmin":
                return fn(*args, **kwargs)
            if role not in roles:
                return jsonify({"error": "Insufficient permissions"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator
