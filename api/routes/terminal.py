"""Remote Terminal — dashboard sends commands, agent executes them."""
import hashlib
import logging
from datetime import datetime, timezone, timedelta

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from extensions import db
from models.device import Device
from models.audit import AgentToken, AuditLog
from models.terminal import TerminalSession, TerminalCommand, TerminalOutput

logger = logging.getLogger(__name__)
terminal_bp = Blueprint("terminal", __name__)

_SESSION_IDLE_TIMEOUT = timedelta(minutes=30)
_MAX_OUTPUT_BYTES = 512 * 1024  # 512 KB per session
_STUCK_CMD_TIMEOUT = timedelta(minutes=3)


def _require_role(*roles):
    claims = get_jwt()
    if claims.get("role") == "superadmin":
        return None
    if claims.get("role") not in roles:
        return jsonify({"error": "Insufficient permissions"}), 403
    return None


def _get_device_by_token(device_id: str):
    """Validate agent Bearer token. Returns (device, agent_token) or (None, None)."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None, None
    token = auth[7:]
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    agent_token = AgentToken.query.filter_by(
        device_id=device_id, token_hash=token_hash, is_revoked=False
    ).first()
    if not agent_token:
        return None, None
    now = datetime.now(timezone.utc)
    if agent_token.expires_at:
        exp = agent_token.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= now:
            return None, None
    agent_token.last_used_at = now
    db.session.add(agent_token)
    return db.session.get(Device, device_id), agent_token


def _check_session_owner(session, user_id: str):
    """Technicians may only interact with their own sessions; admins/superadmins see all."""
    claims = get_jwt()
    if claims.get("role") in ("admin", "superadmin"):
        return None
    if session.user_id != user_id:
        return jsonify({"error": "Session not found"}), 404
    return None


def _audit(action, resource_id, payload=None, user_id=None):
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type="terminal",
        resource_id=resource_id,
        ip_address=request.remote_addr,
        payload=payload,
    )
    db.session.add(entry)


def _expire_idle_sessions():
    """Mark sessions idle > 30 min as closed; reset stuck 'running' commands to 'pending'."""
    now = datetime.now(timezone.utc)
    cutoff = now - _SESSION_IDLE_TIMEOUT
    stale = TerminalSession.query.filter(
        TerminalSession.status == "active",
        TerminalSession.last_activity_at < cutoff,
    ).all()
    for s in stale:
        s.status = "closed"
        s.closed_at = now

    # Reset commands stuck as 'running' for longer than _STUCK_CMD_TIMEOUT
    # (happens when agent process is killed mid-execution)
    stuck_cutoff = now - _STUCK_CMD_TIMEOUT
    stuck = TerminalCommand.query.filter(
        TerminalCommand.status == "running",
        TerminalCommand.picked_up_at < stuck_cutoff,
    ).all()
    for cmd in stuck:
        cmd.status = "pending"
        cmd.picked_up_at = None


# ── Dashboard endpoints (JWT) ─────────────────────────────────────────────────

@terminal_bp.route("/sessions", methods=["POST"])
@jwt_required()
def create_session():
    err = _require_role("admin", "technician")
    if err:
        return err

    data = request.get_json(silent=True) or {}
    device_id = data.get("device_id", "").strip()
    if not device_id:
        return jsonify({"error": "device_id required"}), 400

    device = db.session.get(Device, device_id)
    if not device:
        return jsonify({"error": "Device not found"}), 404
    if device.is_agentless:
        return jsonify({"error": "Remote terminal not available for agentless devices"}), 400
    claims = get_jwt()
    if claims.get("role") == "client" and device.customer_id != claims.get("customer_id"):
        return jsonify({"error": "Device not found"}), 404

    user_id = get_jwt_identity()

    # Close any existing active session for this user+device
    _expire_idle_sessions()
    existing = TerminalSession.query.filter_by(
        device_id=device_id, user_id=user_id, status="active"
    ).first()
    if existing:
        existing.status = "closed"
        existing.closed_at = datetime.now(timezone.utc)

    session = TerminalSession(device_id=device_id, user_id=user_id)
    # Add system welcome message
    db.session.add(session)
    db.session.flush()  # get session.id

    welcome = TerminalOutput(
        session_id=session.id,
        content=f"Connected to {device.hostname or device_id}. Commands run in agent context.\r\n",
        stream="system",
    )
    db.session.add(welcome)
    _audit("terminal_open", session.id, {"device_id": device_id}, user_id)
    db.session.commit()

    logger.info("Terminal session %s opened by user %s on device %s", session.id, user_id, device_id)
    return jsonify(session.to_dict()), 201


@terminal_bp.route("/sessions/<session_id>", methods=["GET"])
@jwt_required()
def get_session(session_id):
    err = _require_role("admin", "technician")
    if err:
        return err
    session = db.get_or_404(TerminalSession, session_id)
    err = _check_session_owner(session, get_jwt_identity())
    if err:
        return err
    return jsonify(session.to_dict()), 200


@terminal_bp.route("/sessions/<session_id>", methods=["DELETE"])
@jwt_required()
def close_session(session_id):
    err = _require_role("admin", "technician")
    if err:
        return err
    session = db.get_or_404(TerminalSession, session_id)
    user_id = get_jwt_identity()
    err = _check_session_owner(session, user_id)
    if err:
        return err
    session.status = "closed"
    session.closed_at = datetime.now(timezone.utc)
    _audit("terminal_close", session_id, None, user_id)
    db.session.commit()
    return jsonify({"message": "Session closed"}), 200


@terminal_bp.route("/sessions/<session_id>/commands", methods=["POST"])
@jwt_required()
def send_command(session_id):
    err = _require_role("admin", "technician")
    if err:
        return err

    session = db.get_or_404(TerminalSession, session_id)
    user_id = get_jwt_identity()
    err = _check_session_owner(session, user_id)
    if err:
        return err
    if session.status != "active":
        return jsonify({"error": "Session is closed"}), 400

    data = request.get_json(silent=True) or {}
    command_text = (data.get("command") or "").strip()
    if not command_text:
        return jsonify({"error": "command required"}), 400
    if len(command_text) > 2000:
        return jsonify({"error": "Command too long (max 2000 chars)"}), 400
    cmd = TerminalCommand(session_id=session_id, command=command_text)
    session.last_activity_at = datetime.now(timezone.utc)

    # Echo the command into output so dashboard shows it
    echo = TerminalOutput(
        session_id=session_id,
        content=f"$ {command_text}\r\n",
        stream="system",
        command_id=None,
    )
    db.session.add(cmd)
    db.session.flush()
    echo.command_id = cmd.id
    db.session.add(echo)

    _audit("terminal_command", session_id, {"command": command_text}, user_id)
    db.session.commit()

    logger.info("Terminal cmd queued session=%s cmd_id=%s", session_id, cmd.id)
    return jsonify(cmd.to_dict()), 201


@terminal_bp.route("/sessions/<session_id>/output", methods=["GET"])
@jwt_required()
def get_output(session_id):
    err = _require_role("admin", "technician")
    if err:
        return err

    session = db.get_or_404(TerminalSession, session_id)
    err = _check_session_owner(session, get_jwt_identity())
    if err:
        return err
    after = request.args.get("after", 0, type=int)

    rows = (
        TerminalOutput.query
        .filter(TerminalOutput.session_id == session_id, TerminalOutput.id > after)
        .order_by(TerminalOutput.id)
        .limit(200)
        .all()
    )
    pending_count = TerminalCommand.query.filter_by(
        session_id=session_id, status="pending"
    ).count()
    return jsonify({
        "session": session.to_dict(),
        "output": [r.to_dict() for r in rows],
        "pending_commands": pending_count,
    }), 200


# ── Agent endpoints (Agent Bearer token) ─────────────────────────────────────

@terminal_bp.route("/agent/<device_id>/sessions", methods=["GET"])
def agent_get_sessions(device_id):
    """Agent polls this every few seconds to see if it has active terminal sessions."""
    device, _ = _get_device_by_token(device_id)
    if not device:
        return jsonify({"error": "Unauthorized"}), 401

    _expire_idle_sessions()
    db.session.commit()

    active = TerminalSession.query.filter_by(device_id=device_id, status="active").all()
    result = []
    for s in active:
        pending = (
            TerminalCommand.query
            .filter_by(session_id=s.id, status="pending")
            .order_by(TerminalCommand.sent_at)
            .first()
        )
        result.append({
            "session_id": s.id,
            "pending_command": pending.to_dict() if pending else None,
        })

    return jsonify({"sessions": result}), 200


@terminal_bp.route("/agent/<device_id>/commands/<command_id>/running", methods=["PUT"])
def agent_command_running(device_id, command_id):
    """Agent marks command as picked up / running."""
    device, _ = _get_device_by_token(device_id)
    if not device:
        return jsonify({"error": "Unauthorized"}), 401

    cmd = db.get_or_404(TerminalCommand, command_id)
    if cmd.status != "pending":
        return jsonify({"error": "Command not pending"}), 400

    cmd.status = "running"
    cmd.picked_up_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"ok": True}), 200


@terminal_bp.route("/agent/<device_id>/commands/<command_id>/output", methods=["POST"])
def agent_post_output(device_id, command_id):
    """Agent streams output chunks back for a command."""
    device, _ = _get_device_by_token(device_id)
    if not device:
        return jsonify({"error": "Unauthorized"}), 401

    cmd = db.get_or_404(TerminalCommand, command_id)
    data = request.get_json(silent=True) or {}
    content = data.get("content", "")
    stream = data.get("stream", "stdout")  # stdout | stderr

    if content:
        # Guard against runaway output
        total = db.session.execute(
            db.text("SELECT COALESCE(SUM(LENGTH(content)),0) FROM terminal_outputs WHERE session_id=:sid"),
            {"sid": cmd.session_id},
        ).scalar() or 0
        if total < _MAX_OUTPUT_BYTES:
            out = TerminalOutput(
                session_id=cmd.session_id,
                command_id=command_id,
                content=content,
                stream=stream,
            )
            db.session.add(out)

        # Update session activity
        sess = db.session.get(TerminalSession, cmd.session_id)
        if sess:
            sess.last_activity_at = datetime.now(timezone.utc)

        db.session.commit()

    return jsonify({"ok": True}), 200


@terminal_bp.route("/agent/<device_id>/commands/<command_id>/done", methods=["PUT"])
def agent_command_done(device_id, command_id):
    """Agent marks command complete (with optional exit code)."""
    device, _ = _get_device_by_token(device_id)
    if not device:
        return jsonify({"error": "Unauthorized"}), 401

    cmd = db.get_or_404(TerminalCommand, command_id)
    data = request.get_json(silent=True) or {}
    exit_code = data.get("exit_code", 0)

    cmd.status = "done" if exit_code == 0 else "error"
    cmd.completed_at = datetime.now(timezone.utc)

    # Append exit code footer when non-zero
    if exit_code != 0:
        footer = TerminalOutput(
            session_id=cmd.session_id,
            command_id=command_id,
            content=f"\r\n[Exit code: {exit_code}]\r\n",
            stream="system",
        )
        db.session.add(footer)

    db.session.commit()
    return jsonify({"ok": True}), 200
