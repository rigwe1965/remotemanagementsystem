"""Shared Anthropic client construction — extracted because the AI ticket-triage
Celery task (services/ticket_triage_service.py) is a second call site alongside
routes/assistant.py, per this codebase's convention of extracting shared logic
only once there are two callers."""
import os


def get_anthropic_client():
    """Lazy-imports anthropic and returns a configured client. Raises RuntimeError
    (not an API error) if ANTHROPIC_API_KEY is unset, so callers can distinguish
    "not configured" from a real API failure and handle each appropriately."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


def get_model(env_var: str, default: str) -> str:
    return os.getenv(env_var, default)
