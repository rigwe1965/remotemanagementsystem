"""Claude tool-use definitions + dispatch for the AI assistant.

Design rules (see plan doc for full rationale):
  - Tool input schemas NEVER include role/customer_id/user_id — those are always
    derived server-side from the caller's JWT via ToolCtx, never accepted from the
    model or from a stored AiPendingAction row.
  - Read tools execute immediately inline (safe, no state change).
  - Mutating tools are always staged as an AiPendingAction and require an explicit
    user confirm via POST /api/assistant/actions/<id>/confirm — never auto-executed.
"""
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from extensions import db
from models.ai_conversation import AiPendingAction
from services import fleet_query_service, device_query_service, ticket_service, alert_service, script_service
from services.ai_prompt import danger_scan
from utils.rate_limit import check_and_increment


@dataclass
class ToolCtx:
    user_id: str
    role: str
    customer_id: str = None


@dataclass
class MutatingToolHandler:
    """One entry per mutating tool, in one place — summarizer, executor, and
    rate limit together, instead of three parallel name-keyed structures that
    could silently drift out of sync (e.g. a new tool shipping without a
    rate limit because the corresponding _TOOL_RATE_LIMITS entry was missed).

    rate_limit mirrors the underlying human-facing route's own @limiter.limit
    (script run 5/min, reboot/shutdown effectively 2/min, ticket create
    20/min) — required here because calling the service function directly
    bypasses the route decorator entirely."""
    summarize: callable  # (tool_input: dict) -> str
    execute: callable     # (tool_input: dict, ctx: ToolCtx) -> (result_dict_or_None, error_or_None)
    rate_limit: tuple = None  # (max_calls, window_seconds)


READ_TOOLS = {"get_fleet_summary", "list_devices", "get_device_status", "list_alerts"}

MUTATING_TOOL_HANDLERS: dict[str, MutatingToolHandler] = {
    "create_ticket": MutatingToolHandler(
        summarize=lambda ti: f"Create ticket: \"{ti.get('title', '')[:80]}\" (priority: {ti.get('priority', 'medium')})",
        execute=lambda ti, ctx: ticket_service.create_ticket_service(
            ctx.user_id, ctx.role, ctx.customer_id,
            title=ti.get("title", ""), description=ti.get("description"),
            customer_id=ti.get("customer_id"), device_id=ti.get("device_id"),
            priority=ti.get("priority", "medium"), source="ai_assistant",
        ),
        rate_limit=(20, 60),
    ),
    "acknowledge_alert": MutatingToolHandler(
        summarize=lambda ti: f"Acknowledge alert {ti.get('alert_id', '')}",
        execute=lambda ti, ctx: alert_service.acknowledge_alert_service(
            ctx.user_id, ctx.role, ctx.customer_id, ti.get("alert_id", "")),
        rate_limit=(30, 60),
    ),
    "resolve_alert": MutatingToolHandler(
        summarize=lambda ti: f"Resolve alert {ti.get('alert_id', '')}",
        execute=lambda ti, ctx: alert_service.resolve_alert_service(
            ctx.user_id, ctx.role, ctx.customer_id, ti.get("alert_id", ""), ti.get("resolution_note")),
        rate_limit=(30, 60),
    ),
    "run_builtin_action": MutatingToolHandler(
        summarize=lambda ti: (
            f"Run '{ti.get('action', '')}' on {len(ti.get('device_ids', []))} "
            f"device(s): {', '.join(ti.get('device_ids', [])[:5])}"
        ),
        execute=lambda ti, ctx: script_service.run_builtin_action_service(
            ctx.user_id, ctx.role, ctx.customer_id, ti.get("device_ids", []), ti.get("action", "")),
        rate_limit=(2, 60),
    ),
    "run_script": MutatingToolHandler(
        summarize=lambda ti: f"Run script {ti.get('script_id', '')} on {len(ti.get('device_ids', []))} device(s)",
        execute=lambda ti, ctx: script_service.run_script_service(
            ctx.user_id, ctx.role, ctx.customer_id, ti.get("script_id", ""), ti.get("device_ids", [])),
        rate_limit=(5, 60),
    ),
}

MUTATING_TOOLS = set(MUTATING_TOOL_HANDLERS)

TOOL_DEFINITIONS = [
    {
        "name": "get_fleet_summary",
        "description": "Get a real-time summary of the fleet: device counts (total/online/offline/critical/warning), "
                       "open alert counts, open ticket counts, and customer count. Scoped automatically to the "
                       "caller's own organisation if they are a client-role user.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_devices",
        "description": "List devices, optionally filtered. Use this to answer questions like 'which devices are "
                       "offline' or 'show me critical devices'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "is_online": {"type": "boolean", "description": "Filter by online status"},
                "status": {"type": "string", "enum": ["healthy", "warning", "critical"], "description": "Filter by device health status"},
                "platform": {"type": "string", "description": "Filter by OS platform, e.g. windows/mac/linux/android/ios"},
                "q": {"type": "string", "description": "Search by hostname substring"},
            },
        },
    },
    {
        "name": "get_device_status",
        "description": "Get full detail (metrics, status, last seen) for one device by its device_id. "
                       "Call list_devices first if you only know the hostname.",
        "input_schema": {
            "type": "object",
            "properties": {"device_id": {"type": "string"}},
            "required": ["device_id"],
        },
    },
    {
        "name": "list_alerts",
        "description": "List alerts, optionally filtered by status or severity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["open", "acknowledged", "resolved"]},
                "severity": {"type": "string", "enum": ["info", "warning", "critical"]},
                "limit": {"type": "integer", "description": "Max results, default 20, max 50"},
            },
        },
    },
    {
        "name": "create_ticket",
        "description": "Create a new support ticket. This is a MUTATING action — it will be staged for the "
                       "user to confirm before it is actually created.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "customer_id": {"type": "string", "description": "Required for staff roles; ignored/auto-filled for client role"},
                "device_id": {"type": "string"},
                "priority": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
            },
            "required": ["title"],
        },
    },
    {
        "name": "acknowledge_alert",
        "description": "Acknowledge an open alert. MUTATING — staged for confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {"alert_id": {"type": "string"}},
            "required": ["alert_id"],
        },
    },
    {
        "name": "resolve_alert",
        "description": "Resolve an alert. MUTATING — staged for confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "alert_id": {"type": "string"},
                "resolution_note": {"type": "string"},
            },
            "required": ["alert_id"],
        },
    },
    {
        "name": "run_builtin_action",
        "description": "Run a built-in maintenance action (reboot, shutdown, clean_temp, defrag, check_disk, "
                       "restore_point, clear_browser, software_rescan) on one or more devices. MUTATING — staged "
                       "for confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "device_ids": {"type": "array", "items": {"type": "string"}},
                "action": {"type": "string", "enum": list(script_service.BUILTIN_ACTIONS)},
            },
            "required": ["device_ids", "action"],
        },
    },
    {
        "name": "run_script",
        "description": "Run a specific custom or built-in script (by script_id) on one or more devices. "
                       "MUTATING — staged for confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "script_id": {"type": "string"},
                "device_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["script_id", "device_ids"],
        },
    },
]


def tools_for_page(page: str, agentic: bool) -> list:
    from services.ai_prompt import _ACTION_AWARE_PAGES
    if not agentic:
        return []
    read_only = [t for t in TOOL_DEFINITIONS if t["name"] in READ_TOOLS]
    if page in _ACTION_AWARE_PAGES:
        return TOOL_DEFINITIONS
    return read_only


def execute_read_tool(name: str, tool_input: dict, ctx: ToolCtx) -> dict:
    if name == "get_fleet_summary":
        return fleet_query_service.get_fleet_summary(ctx.role, ctx.customer_id)
    if name == "list_devices":
        return {"devices": device_query_service.list_devices_for_assistant(
            ctx.role, ctx.customer_id,
            is_online=tool_input.get("is_online"), status=tool_input.get("status"),
            platform=tool_input.get("platform"), q=tool_input.get("q"),
        )}
    if name == "get_device_status":
        device, err = device_query_service.get_device_status_for_assistant(
            ctx.role, ctx.customer_id, tool_input.get("device_id", ""))
        if err:
            return {"error": err[0]}
        return device
    if name == "list_alerts":
        return {"alerts": fleet_query_service.list_alerts_for_assistant(
            ctx.role, ctx.customer_id,
            status=tool_input.get("status"), severity=tool_input.get("severity"),
            limit=tool_input.get("limit", 20),
        )}
    return {"error": f"Unknown read tool '{name}'"}


def _danger_scan(tool_input: dict) -> bool:
    text = " ".join(str(v) for v in tool_input.values())
    return danger_scan(text)


def _summarize(name: str, tool_input: dict) -> str:
    handler = MUTATING_TOOL_HANDLERS.get(name)
    if handler:
        return handler.summarize(tool_input)
    return f"{name}({tool_input})"


def stage_mutating_tool(name: str, tool_input: dict, ctx: ToolCtx, conversation_id: str,
                         tool_use_id: str) -> AiPendingAction:
    ttl_seconds = int(os.getenv("AI_ASSISTANT_ACTION_TTL_SECONDS", "300"))
    pending = AiPendingAction(
        conversation_id=conversation_id,
        user_id=ctx.user_id,
        tool_name=name,
        tool_input=tool_input,
        tool_use_id=tool_use_id,
        summary=_summarize(name, tool_input)[:500],
        contains_warning=_danger_scan(tool_input),
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
    )
    db.session.add(pending)
    db.session.commit()
    return pending


def execute_pending_action(pending: AiPendingAction, ctx: ToolCtx):
    """Re-derives permissions fresh from ctx (built from the CURRENT caller's JWT at
    confirm-time — never trusts anything on the pending row except tool_name/tool_input).
    Returns (result_dict, error_or_None)."""
    handler = MUTATING_TOOL_HANDLERS.get(pending.tool_name)
    if not handler:
        return None, (f"Unknown tool '{pending.tool_name}'", 400)

    if handler.rate_limit:
        max_calls, window = handler.rate_limit
        allowed = check_and_increment(f"rmm:ai:toolrate:{ctx.user_id}:{pending.tool_name}", max_calls, window)
        if not allowed:
            return None, ("Rate limit exceeded for this action — please wait a moment.", 429)

    return handler.execute(pending.tool_input or {}, ctx)
