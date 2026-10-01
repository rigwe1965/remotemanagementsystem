"""AI Assistant — agentic chat endpoint for dashboard guidance + fleet actions.

Phase 1 refactor: prompt/tool logic moved to services/ai_prompt.py + services/ai_tools.py;
conversation persistence added (AiConversation/AiMessage); mutating tool calls are staged
via AiPendingAction and require an explicit confirm/deny call — never auto-executed.
"""
import os
import json
import time
import logging
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from flask_limiter.util import get_remote_address

from extensions import db, limiter
from models.audit import AuditLog
from models.ai_conversation import AiConversation, AiMessage, AiPendingAction
from models.user import User
from utils.usage_tracker import record_event
from services.ai_prompt import (
    build_system_prompt, _RESTRICTED_PAGES, _CODE_BLOCK_RE, _DANGER_PATTERNS,
    _PAGE_ACTIONS, _PAGE_ALLOWED_ROLES,
)
from services.ai_tools import ToolCtx, READ_TOOLS, tools_for_page, execute_read_tool, stage_mutating_tool, execute_pending_action

log = logging.getLogger(__name__)

assistant_bp = Blueprint("assistant", __name__)

_MAX_TOOL_ITERATIONS = int(os.getenv("AI_ASSISTANT_MAX_TOOL_ITERATIONS", "4"))
_MAX_TOKENS = int(os.getenv("AI_ASSISTANT_MAX_TOKENS", "900"))
_HISTORY_TURNS = int(os.getenv("AI_ASSISTANT_HISTORY_TURNS", "10"))


def _agentic_enabled() -> bool:
    return os.getenv("AI_ASSISTANT_AGENTIC_ENABLED", "true").lower() != "false"


def _per_user_key():
    try:
        uid = get_jwt_identity()
        if uid:
            return f"user:{uid}"
    except Exception:
        pass
    return get_remote_address()


def _build_ctx() -> ToolCtx:
    claims = get_jwt()
    role = claims.get("role", "viewer")
    uid = get_jwt_identity()
    customer_id = None
    if role == "client":
        user = db.session.get(User, uid)
        customer_id = user.customer_id if user else None
    return ToolCtx(user_id=uid, role=role, customer_id=customer_id)


def _get_or_create_conversation(user_id: str, page: str) -> AiConversation:
    conv = (
        AiConversation.query
        .filter_by(user_id=user_id, is_archived=False)
        .order_by(AiConversation.updated_at.desc())
        .first()
    )
    if conv:
        conv.page = page
        return conv
    conv = AiConversation(user_id=user_id, page=page)
    db.session.add(conv)
    db.session.flush()
    return conv


def _load_history_messages(conversation_id: str) -> list:
    rows = (
        AiMessage.query
        .filter_by(conversation_id=conversation_id)
        .filter(AiMessage.role.in_(("user", "assistant")))
        .order_by(AiMessage.created_at.desc())
        .limit(_HISTORY_TURNS)
        .all()
    )
    rows.reverse()
    return [{"role": r.role, "content": r.content} for r in rows]


def _audit(user_id, action, resource_type, resource_id, payload):
    try:
        db.session.add(AuditLog(
            user_id=user_id, action=action, resource_type=resource_type,
            resource_id=str(resource_id)[:36] if resource_id else None,
            ip_address=request.remote_addr, payload=payload,
        ))
        db.session.commit()
    except Exception:
        log.exception("AI assistant audit log write failed")
        try:
            db.session.rollback()
        except Exception:
            pass


@assistant_bp.route("/chat", methods=["POST"])
@jwt_required()
@limiter.limit("30 per minute", key_func=_per_user_key)
def chat():
    if os.getenv("AI_ASSISTANT_ENABLED", "true").lower() == "false":
        return jsonify({"error": "AI assistant is disabled for this organisation"}), 503

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return jsonify({"error": "AI assistant is not configured — ANTHROPIC_API_KEY missing"}), 503

    body = request.get_json(silent=True) or {}
    message = (body.get("message") or "").strip()
    page = str(body.get("page") or "Overview")[:60]
    raw_context = body.get("context") or {}

    if not message:
        return jsonify({"error": "message is required"}), 400
    if len(message) > 1000:
        message = message[:1000]

    safe_context = {
        str(k)[:60]: str(v)[:300]
        for k, v in raw_context.items()
        if k and v is not None and str(v).strip()
    }

    role = get_jwt().get("role", "viewer")

    # ── Server-side page authorization (previously prompt-text-only) ─────────
    allowed_roles = _PAGE_ALLOWED_ROLES.get(page)
    if allowed_roles and role != "superadmin" and role not in allowed_roles:
        return jsonify({"error": "Insufficient permissions for this page"}), 403

    # ── Inbound danger-pattern scan (previously outbound-reply-only) ─────────
    inbound_warning = any(p.search(message) for p in _DANGER_PATTERNS)

    agentic = _agentic_enabled()
    ctx = _build_ctx()
    conversation = _get_or_create_conversation(ctx.user_id, page)

    system_prompt = build_system_prompt(role, page, safe_context, agentic)
    messages = _load_history_messages(conversation.id)
    messages.append({"role": "user", "content": message})

    db.session.add(AiMessage(conversation_id=conversation.id, role="user", content=message,
                              contains_warning=inbound_warning))
    db.session.commit()

    tools = tools_for_page(page, agentic)
    tool_calls_log = []
    pending_action = None
    final_text = None

    try:
        from utils.ai_client import get_anthropic_client, get_model
        client = get_anthropic_client()
        model = get_model("AI_ASSISTANT_MODEL", "claude-haiku-4-5-20251001")

        for _ in range(_MAX_TOOL_ITERATIONS):
            create_kwargs = dict(model=model, max_tokens=_MAX_TOKENS, system=system_prompt, messages=messages)
            if tools:
                create_kwargs["tools"] = tools
            _t0 = time.perf_counter()
            resp = client.messages.create(**create_kwargs)
            _usage = getattr(resp, "usage", None)
            record_event(
                service="ai_assistant", feature=page, user_id=ctx.user_id,
                input_tokens=getattr(_usage, "input_tokens", None) if _usage else None,
                output_tokens=getattr(_usage, "output_tokens", None) if _usage else None,
                status="success", latency_ms=int((time.perf_counter() - _t0) * 1000), model=model,
            )

            assistant_blocks = []
            for b in resp.content:
                btype = getattr(b, "type", None)
                if btype == "tool_use":
                    assistant_blocks.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
                else:
                    assistant_blocks.append({"type": "text", "text": getattr(b, "text", "")})
            messages.append({"role": "assistant", "content": assistant_blocks})

            if resp.stop_reason != "tool_use":
                final_text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
                break

            tool_results = []
            staged_this_round = False
            for block in resp.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                tool_calls_log.append({"tool_name": block.name, "input": block.input, "tool_use_id": block.id})
                if block.name in READ_TOOLS:
                    result = execute_read_tool(block.name, block.input or {}, ctx)
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id,
                                          "content": json.dumps(result, default=str)})
                else:
                    pending_action = stage_mutating_tool(block.name, block.input or {}, ctx,
                                                          conversation.id, block.id)
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id,
                                          "content": json.dumps({"status": "pending_user_confirmation",
                                                                  "summary": pending_action.summary})})
                    staged_this_round = True

            messages.append({"role": "user", "content": tool_results})
            if staged_this_round:
                # Do exactly one more turn so Claude can acknowledge the staged action in
                # text, then stop — never let it loop past a staged mutation unattended.
                create_kwargs["messages"] = messages
                _t0 = time.perf_counter()
                resp2 = client.messages.create(**create_kwargs)
                _usage2 = getattr(resp2, "usage", None)
                record_event(
                    service="ai_assistant", feature=page, user_id=ctx.user_id,
                    input_tokens=getattr(_usage2, "input_tokens", None) if _usage2 else None,
                    output_tokens=getattr(_usage2, "output_tokens", None) if _usage2 else None,
                    status="success", latency_ms=int((time.perf_counter() - _t0) * 1000), model=model,
                )
                final_text = "".join(b.text for b in resp2.content if getattr(b, "type", None) == "text")
                break
        else:
            final_text = "I need more steps than allowed to complete this — please narrow your request."

        if not final_text:
            final_text = "I couldn't generate a response. Please try again."
    except Exception as exc:
        exc_name = type(exc).__name__
        db.session.rollback()
        record_event(service="ai_assistant", feature=page, user_id=ctx.user_id,
                     status="error", error=f"{exc_name}: {str(exc)[:200]}")
        if "AuthenticationError" in exc_name or "Authentication" in str(exc):
            return jsonify({"error": "AI service configuration error — check ANTHROPIC_API_KEY"}), 503
        if "RateLimitError" in exc_name or "rate_limit" in str(exc).lower():
            return jsonify({"error": "AI service is busy. Please try again in a moment."}), 429
        log.exception("AI assistant chat failed")
        return jsonify({"error": "AI assistant temporarily unavailable"}), 503

    reply = final_text

    if page in _RESTRICTED_PAGES:
        reply = _CODE_BLOCK_RE.sub("[code removed — command suggestions are disabled on this page]", reply)

    contains_warning = inbound_warning or any(p.search(reply) for p in _DANGER_PATTERNS)
    if pending_action and pending_action.contains_warning:
        contains_warning = True
    if contains_warning and not (pending_action and pending_action.contains_warning):
        reply = (
            "**CAUTION:** This response references a potentially destructive operation. "
            "Do not execute without supervisor review.\n\n" + reply
        )

    db.session.add(AiMessage(conversation_id=conversation.id, role="assistant", content=reply,
                              tool_calls=tool_calls_log or None, contains_warning=contains_warning))
    db.session.commit()

    _audit(ctx.user_id, "ai_assistant_chat", "page", page,
           {"msg_len": len(message), "contains_warning": contains_warning, "tool_calls": len(tool_calls_log)})

    suggested = _PAGE_ACTIONS.get(page, [])
    resp_body = {
        "reply": reply,
        "suggested_actions": suggested,
        "contains_warning": contains_warning,
        "conversation_id": conversation.id,
    }
    if pending_action:
        resp_body["pending_action"] = {
            "id": pending_action.id,
            "tool_name": pending_action.tool_name,
            "summary": pending_action.summary,
            "contains_warning": pending_action.contains_warning,
            "expires_at": pending_action.expires_at.isoformat(),
        }
    return jsonify(resp_body)


@assistant_bp.route("/conversation", methods=["GET"])
@jwt_required()
def get_conversation():
    uid = get_jwt_identity()
    conv = (
        AiConversation.query
        .filter_by(user_id=uid, is_archived=False)
        .order_by(AiConversation.updated_at.desc())
        .first()
    )
    if not conv:
        return jsonify({"conversation_id": None, "messages": []}), 200
    msgs = (
        AiMessage.query.filter_by(conversation_id=conv.id)
        .order_by(AiMessage.created_at.asc())
        .limit(200)
        .all()
    )
    return jsonify({"conversation_id": conv.id, "messages": [m.to_dict() for m in msgs]}), 200


@assistant_bp.route("/conversation", methods=["DELETE"])
@jwt_required()
def clear_conversation():
    uid = get_jwt_identity()
    conv = (
        AiConversation.query
        .filter_by(user_id=uid, is_archived=False)
        .order_by(AiConversation.updated_at.desc())
        .first()
    )
    if conv:
        conv.is_archived = True
        db.session.commit()
    return jsonify({"message": "Conversation cleared"}), 200


@assistant_bp.route("/actions/<action_id>/confirm", methods=["POST"])
@jwt_required()
@limiter.limit("30 per minute", key_func=_per_user_key)
def confirm_action(action_id):
    uid = get_jwt_identity()
    pending = AiPendingAction.query.filter_by(id=action_id, user_id=uid).first()
    if not pending:
        return jsonify({"error": "Pending action not found"}), 404
    if pending.status != "pending":
        return jsonify({"error": f"Action already {pending.status}"}), 409

    expires_at = pending.expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at and expires_at < datetime.now(timezone.utc):
        pending.status = "expired"
        db.session.commit()
        return jsonify({"error": "This action has expired — ask the assistant to try again"}), 409

    ctx = _build_ctx()
    result, err = execute_pending_action(pending, ctx)
    if err:
        pending.status = "failed"
        pending.result = {"error": err[0]}
        db.session.commit()
        return jsonify({"error": err[0]}), err[1]

    pending.status = "confirmed"
    pending.result = result
    pending.resolved_at = datetime.now(timezone.utc)
    db.session.commit()

    _audit(uid, "ai_tool_call", "ai_pending_action", pending.id,
           {"tool_name": pending.tool_name, "contains_warning": pending.contains_warning,
            "conversation_id": pending.conversation_id})

    return jsonify({"status": "confirmed", "result": result}), 200


@assistant_bp.route("/actions/<action_id>/deny", methods=["POST"])
@jwt_required()
@limiter.limit("30 per minute", key_func=_per_user_key)
def deny_action(action_id):
    uid = get_jwt_identity()
    pending = AiPendingAction.query.filter_by(id=action_id, user_id=uid).first()
    if not pending:
        return jsonify({"error": "Pending action not found"}), 404
    if pending.status != "pending":
        return jsonify({"error": f"Action already {pending.status}"}), 409

    pending.status = "denied"
    pending.resolved_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"status": "denied"}), 200
