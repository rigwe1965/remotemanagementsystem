"""Sign-in lockout that a stranger cannot use to lock the real owner out.

The old rule locked the WHOLE ACCOUNT for 5 minutes after 3 wrong passwords, so anyone who knew an email address could keep
that person out of the system by guessing wrongly every 5 minutes. Now:

* Three wrong passwords (or wrong two-step codes) from ONE address lock that address out of that account for 5 minutes.
  The owner, signing in from another address, is not affected.
* Guessing spread over many addresses is slowed by a second rule: after NET_THRESHOLD failures within NET_WINDOW from addresses
  this account has never signed in from, those unfamiliar addresses are locked. Addresses the account has signed in from
  before (``User.known_ips``) are never caught by this rule, so a real user on a familiar network still gets in.
* A good sign-in from an address, an admin "Unlock", or a completed password reset clears the count.

There is no new table: the counts come from the audit log, which already records every failed sign-in with its address.
The address is only as good as ``utils/client_ip.py`` makes it: behind a proxy that is not configured, all users share one address
and this behaves like the old per-account rule (no worse than before).
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_

from extensions import db
from models.audit import AuditLog

LOCK_THRESHOLD = 3
LOCK_WINDOW = timedelta(minutes=5)
NET_THRESHOLD = 30
NET_WINDOW = timedelta(minutes=15)

FAILURE_ACTIONS = ("login_failed", "mfa_failed")
UNLOCK_ACTION = "login_unlocked"


def _aware(dt):
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _latest(user_id, action, ip=None):
    q = db.session.query(db.func.max(AuditLog.created_at)).filter(AuditLog.user_id == user_id, AuditLog.action == action)
    if ip is not None:
        q = q.filter(AuditLog.ip_address == ip)
    return _aware(q.scalar())


def _later(*times):
    times = [t for t in times if t is not None]
    return max(times) if times else None


def record_unlock(user_id, ip=None):
    """Clear every address's count for this account (admin Unlock, completed password reset)."""
    db.session.add(AuditLog(user_id=user_id, action=UNLOCK_ACTION, resource_type="user", ip_address=ip))


def locked_until(user, ip, now=None):
    """The time until which ``ip`` may not try ``user``'s password, or None when it may."""
    now = now or datetime.now(timezone.utc)
    ip = ip or ""
    unlocked_at = _latest(user.id, UNLOCK_ACTION)

    # Rule 1: three failures from this address since the last thing that cleared them.
    since = _later(now - LOCK_WINDOW, unlocked_at, _latest(user.id, "login_success", ip))
    recent = (
        db.session.query(AuditLog.created_at)
        .filter(AuditLog.user_id == user.id, AuditLog.action.in_(FAILURE_ACTIONS),
                AuditLog.ip_address == ip, AuditLog.created_at > since)
        .order_by(AuditLog.created_at.desc()).limit(LOCK_THRESHOLD).all()
    )
    until = None
    if len(recent) >= LOCK_THRESHOLD:
        until = _aware(recent[LOCK_THRESHOLD - 1][0]) + LOCK_WINDOW

    # Rule 2: many failures from addresses this account has never signed in from. Familiar addresses are exempt.
    known = [k for k in (user.known_ips or []) if k]
    if ip not in known:
        since = _later(now - NET_WINDOW, unlocked_at)
        unfamiliar = AuditLog.ip_address.is_(None) if not known else or_(AuditLog.ip_address.is_(None), ~AuditLog.ip_address.in_(known))
        recent = (
            db.session.query(AuditLog.created_at)
            .filter(AuditLog.user_id == user.id, AuditLog.action.in_(FAILURE_ACTIONS), unfamiliar, AuditLog.created_at > since)
            .order_by(AuditLog.created_at.desc()).limit(NET_THRESHOLD).all()
        )
        if len(recent) >= NET_THRESHOLD:
            net = _aware(recent[NET_THRESHOLD - 1][0]) + NET_WINDOW
            until = _later(until, net)

    return until if until and until > now else None
