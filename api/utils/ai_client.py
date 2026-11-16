"""Shared Anthropic client construction — extracted because the AI ticket-triage
Celery task (services/ticket_triage_service.py) is a second call site alongside
routes/assistant.py, per this codebase's convention of extracting shared logic
only once there are two callers."""
import logging
import os

logger = logging.getLogger(__name__)

# Claude models an operator may choose, with USD per 1M (input, output) tokens. Each was checked against Anthropic's
# Models API for tool use, which both AI features need. Anything else in AI_ASSISTANT_MODEL / AI_TRIAGE_MODEL is ignored
# with a warning and the feature keeps running on its default, so a typo cannot make every request fail.
SUPPORTED_MODELS = {
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
}
# Models that refuse tool_choice {"type": "tool"} / {"type": "any"} (HTTP 400, checked live 2026-11-16). For these the caller
# asks with tool_choice "auto" and says in the prompt that the tool must be used.
NO_FORCED_TOOL_CHOICE = frozenset({"claude-sonnet-5-5", "claude-opus-5-5"})
_warned = set()


def tool_choice_for(model, tool_name):
    """The tool_choice to send so the model returns `tool_name`: forced where the model allows it, otherwise auto."""
    if model in NO_FORCED_TOOL_CHOICE:
        return {"type": "auto"}
    return {"type": "tool", "name": tool_name}


def model_price(model):
    """(input, output) USD per 1M tokens. A model we have no price for is costed at the dearest known price, never cheaper."""
    return SUPPORTED_MODELS.get(model) or (max(p[0] for p in SUPPORTED_MODELS.values()), max(p[1] for p in SUPPORTED_MODELS.values()))


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
    value = os.getenv(env_var, "").strip()
    if not value:
        return default
    if value in SUPPORTED_MODELS:
        return value
    if (env_var, value) not in _warned:
        _warned.add((env_var, value))
        logger.warning("%s=%r is not a supported Claude model; using %s.", env_var, value, default)
    return default
