"""Shared circuit breaker for per-integration Celery sync tasks (PSA, MDM, and any
future integration with the same consecutive-failure-count + auto-disable shape).

Auto-disables an integration after too many consecutive sync failures instead of
retrying a permanently-broken one (e.g. revoked credentials) forever on every beat
cycle. Only this failure-handling tail is shared — each task's actual sync logic
(what gets pulled/pushed) stays in its own file.
"""
import logging

_MAX_CONSECUTIVE_FAILURES = 10


def record_failure_and_retry(task_self, integration, exc, *, label: str, logger: logging.Logger):
    """Call from inside `except Exception as exc:` in a per-integration sync task.
    Rolls back, updates the integration's failure-tracking fields, auto-disables it
    past the threshold, commits, then always raises `task_self.retry(...)` — never
    returns normally."""
    from extensions import db

    logger.error("%s sync failed for %s: %s", label, integration.id, exc)
    db.session.rollback()
    integration.sync_error = str(exc)[:500]
    integration.consecutive_failures = (integration.consecutive_failures or 0) + 1
    if integration.consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
        integration.is_active = False
        logger.warning(
            "Disabling %s integration %s (%s) after %d consecutive failures",
            label, integration.id, integration.name, integration.consecutive_failures,
        )
    db.session.commit()
    raise task_self.retry(exc=exc, countdown=120)
