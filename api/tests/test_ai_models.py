"""Model choice for the AI assistant and ticket triage (utils/ai_client.py)."""
import importlib

import pytest

from utils import ai_client


def test_default_is_used_when_nothing_is_set(monkeypatch):
    monkeypatch.delenv("AI_ASSISTANT_MODEL", raising=False)
    assert ai_client.get_model("AI_ASSISTANT_MODEL", "claude-haiku-4-5-20251001") == "claude-haiku-4-5-20251001"


@pytest.mark.parametrize("model", sorted(ai_client.SUPPORTED_MODELS))
def test_every_supported_model_is_accepted(monkeypatch, model):
    monkeypatch.setenv("AI_ASSISTANT_MODEL", model)
    assert ai_client.get_model("AI_ASSISTANT_MODEL", "claude-haiku-4-5-20251001") == model


def test_a_mistyped_model_falls_back_to_the_default(monkeypatch, caplog):
    monkeypatch.setenv("AI_TRIAGE_MODEL", "claude-sonet-5-5")
    assert ai_client.get_model("AI_TRIAGE_MODEL", "claude-haiku-4-5-20251001") == "claude-haiku-4-5-20251001"


def test_blank_value_means_default(monkeypatch):
    monkeypatch.setenv("AI_TRIAGE_MODEL", "  ")
    assert ai_client.get_model("AI_TRIAGE_MODEL", "claude-haiku-4-5-20251001") == "claude-haiku-4-5-20251001"


def test_prices_rise_from_haiku_to_opus():
    h, s, o = (ai_client.model_price(m) for m in ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"))
    assert h < s < o


def test_an_unpriced_model_costs_the_dearest_known_price():
    top = (max(p[0] for p in ai_client.SUPPORTED_MODELS.values()), max(p[1] for p in ai_client.SUPPORTED_MODELS.values()))
    assert ai_client.model_price("claude-unpriced") == top


def test_cost_estimate_follows_the_model_used(monkeypatch):
    monkeypatch.delenv("AI_ASSISTANT_COST_PER_1M_INPUT", raising=False)
    monkeypatch.delenv("AI_ASSISTANT_COST_PER_1M_OUTPUT", raising=False)
    monkeypatch.setenv("AI_ASSISTANT_MODEL", "claude-haiku-4-5-20251001")
    import utils.usage_tracker as ut
    ut = importlib.reload(ut)
    # triage on Opus is costed at Opus's price even though the assistant runs on Haiku
    assert ut.estimate_cost("claude-opus-5-5", 1_000_000, 1_000_000) == pytest.approx(24.0)
    assert ut.estimate_cost("claude-haiku-4-5-20251001", 1_000_000, 1_000_000) == pytest.approx(6.0)


def test_explicit_cost_override_still_wins(monkeypatch):
    monkeypatch.setenv("AI_ASSISTANT_MODEL", "claude-sonnet-5-5")
    monkeypatch.setenv("AI_ASSISTANT_COST_PER_1M_INPUT", "7")
    monkeypatch.setenv("AI_ASSISTANT_COST_PER_1M_OUTPUT", "9")
    import utils.usage_tracker as ut
    ut = importlib.reload(ut)
    assert ut.estimate_cost("claude-sonnet-5-5", 1_000_000, 1_000_000) == pytest.approx(16.0)


def test_forced_tool_choice_is_used_only_where_the_model_allows_it():
    assert ai_client.tool_choice_for("claude-haiku-4-5-20251001", "t") == {"type": "tool", "name": "t"}
    assert ai_client.tool_choice_for("claude-haiku-5-5", "t") == {"type": "tool", "name": "t"}
    for m in ("claude-sonnet-5-5", "claude-opus-5-5"):
        assert ai_client.tool_choice_for(m, "t") == {"type": "auto"}


def test_triage_request_adapts_to_the_chosen_model(app, monkeypatch):
    """The triage call must never send a forced tool_choice to a model that rejects it."""
    from unittest.mock import MagicMock
    import services.ticket_triage_service as svc

    sent = {}

    def fake_create(**kw):
        sent.update(kw)
        raise RuntimeError("stop here")  # the request is all this test needs

    client = MagicMock(); client.messages.create.side_effect = fake_create
    monkeypatch.setattr(svc, "get_anthropic_client", lambda: client)
    monkeypatch.setenv("AI_TRIAGE_MODEL", "claude-opus-5-5")
    ticket = MagicMock(); ticket.id = "t1"
    monkeypatch.setattr(svc, "build_triage_prompt", lambda t: ("SYS", "hello"))
    monkeypatch.setattr(svc, "check_and_increment", lambda *a, **k: True)
    monkeypatch.setattr(svc, "record_event", lambda *a, **k: None)
    fake_db = MagicMock(); fake_db.session.get.return_value = ticket
    monkeypatch.setattr(svc, "db", fake_db)
    try:
        with app.app_context():
            svc.run_triage("t1")
    except Exception:
        pass
    assert sent.get("model") == "claude-opus-5-5"
    assert sent.get("tool_choice") == {"type": "auto"}
    assert "categorize_ticket" in sent.get("system", "")


def test_the_default_model_is_haiku_5_5_and_can_be_forced_to_use_a_tool():
    assert ai_client.DEFAULT_MODEL == "claude-haiku-5-5"
    assert ai_client.DEFAULT_MODEL in ai_client.SUPPORTED_MODELS
    assert ai_client.tool_choice_for(ai_client.DEFAULT_MODEL, "t") == {"type": "tool", "name": "t"}, "triage forces its tool"
    assert ai_client.model_price(ai_client.DEFAULT_MODEL) == min(ai_client.SUPPORTED_MODELS.values())


def test_no_api_code_writes_its_own_default_model():
    """The default lives in utils/ai_client.py only (DEFAULT_MODEL), so it cannot drift between the assistant, triage and
    the usage costing again (they all said claude-haiku-4-5-20251001 before)."""
    import re
    from pathlib import Path
    api = Path(__file__).resolve().parents[1]
    offenders = []
    for path in api.rglob("*.py"):
        rel = path.relative_to(api)
        if rel.parts[0] in ("tests", "venv", ".venv") or rel == Path("utils/ai_client.py"):
            continue
        if re.search(r"""["']claude-(haiku|sonnet|opus)-[0-9a-z.-]+["']""", path.read_text(encoding="utf-8", errors="replace")):
            offenders.append(str(rel))
    assert offenders == []
