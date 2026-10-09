"""SSE event stream + recent-events polling endpoint."""
import json
import logging
import time

from flask import Blueprint, Response, request, jsonify, stream_with_context, current_app
from flask_jwt_extended import jwt_required, decode_token, get_jwt
from jwt.exceptions import ExpiredSignatureError

logger = logging.getLogger(__name__)
events_bp = Blueprint("events", __name__)

_MAX_STREAM_SECONDS = 60   # SSE connection max duration before client reconnects
_KEEPALIVE_SECONDS = 15    # SSE keepalive comment interval


def _validate_token_param(token: str) -> tuple:
    """Decode JWT from query param. Returns (claims_dict, error_str)."""
    if not token:
        return None, "token required"
    try:
        claims = decode_token(token)
        return claims, None
    except ExpiredSignatureError:
        return None, "token expired"
    except Exception as exc:
        # Generic message to an unauthenticated caller (this endpoint has no
        # @jwt_required() — it reads ?token= itself since EventSource can't set
        # headers, so this branch is reachable pre-auth). Full detail server-side only.
        logger.debug("SSE token validation failed: %s", exc)
        return None, "invalid token"


@events_bp.route("/stream", methods=["GET"])
def stream():
    """
    SSE endpoint for real-time event push.
    Auth: ?token=<access_jwt>  (EventSource API cannot set custom headers)
    Roles: admin, technician, viewer, superadmin
    Client reconnects automatically every 60s (browser EventSource default).
    """
    token = request.args.get("token", "")
    claims, err = _validate_token_param(token)
    if err:
        return jsonify({"error": err}), 401

    # Extract role from JWT sub_claims (flask-jwt-extended stores additional claims there)
    role = (
        claims.get("role")
        or (claims.get("sub_claims") or {}).get("role")
        or ""
    )
    if role not in ("admin", "technician", "viewer", "superadmin"):
        return jsonify({"error": "Forbidden"}), 403

    def _generate():
        ps = None
        try:
            from utils.events import new_pubsub
            ps = new_pubsub()
        except Exception as exc:
            logger.warning("SSE: could not connect to Redis: %s", exc)
            yield "data: {\"type\":\"error\",\"data\":{\"msg\":\"Redis unavailable\"}}\n\n"
            return

        yield f"data: {json.dumps({'type': 'connected', 'data': {}})}\n\n"

        deadline = time.monotonic() + _MAX_STREAM_SECONDS
        last_keepalive = time.monotonic()

        try:
            while time.monotonic() < deadline:
                msg = ps.get_message(timeout=1.0)
                if msg and msg.get("type") == "message":
                    yield f"data: {msg['data']}\n\n"
                    last_keepalive = time.monotonic()
                elif time.monotonic() - last_keepalive >= _KEEPALIVE_SECONDS:
                    yield ": keepalive\n\n"
                    last_keepalive = time.monotonic()
        except GeneratorExit:
            pass
        except Exception as exc:
            logger.warning("SSE stream error: %s", exc)
        finally:
            try:
                ps.unsubscribe()
                ps.close()
            except Exception:
                pass

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",   # disable nginx/proxy buffering
        "Connection": "keep-alive",
    }
    return Response(
        stream_with_context(_generate()),
        mimetype="text/event-stream",
        headers=headers,
    )


@events_bp.route("/recent", methods=["GET"])
@jwt_required()
def recent_events():
    """Return last N events for dashboard polling fallback. Staff only: the event bus is
    not tenant-partitioned, so client-role callers must not see it."""
    if get_jwt().get("role") not in ("admin", "technician", "viewer", "superadmin"):
        return jsonify({"error": "Insufficient permissions"}), 403
    limit = min(request.args.get("limit", 20, type=int), 100)
    from utils.events import get_recent_events
    return jsonify(get_recent_events(limit)), 200
