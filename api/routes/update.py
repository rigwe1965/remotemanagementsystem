"""Agent auto-update endpoints."""
import hashlib
import logging
import os
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, Response, stream_with_context
from flask_jwt_extended import jwt_required

from models.audit import AgentToken

logger = logging.getLogger(__name__)
update_bp = Blueprint("update", __name__)


def _get_latest_version() -> str:
    return os.getenv("LATEST_AGENT_VERSION", "1.0.0").strip()


def _get_update_path() -> str:
    return os.getenv("AGENT_UPDATE_PATH", "").strip()


def _file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _any_valid_agent_token() -> bool:
    """Returns True if request carries a valid (non-revoked) agent Bearer token."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False
    token = auth[7:]
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    at = AgentToken.query.filter_by(token_hash=token_hash, is_revoked=False).first()
    if at is None:
        return False
    if at.expires_at:
        exp = at.expires_at
        if exp.tzinfo is None:  # SQLite returns naive datetimes; treat as UTC
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= datetime.now(timezone.utc):
            return False
    return True


def _ver_tuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.strip().split("."))
    except Exception:
        return (0,)


# ── Dashboard endpoint (JWT) ──────────────────────────────────────────────────

@update_bp.route("/info", methods=["GET"])
@jwt_required()
def update_info():
    """Return latest agent version info for dashboard display."""
    latest = _get_latest_version()
    update_path = _get_update_path()
    download_available = bool(update_path and os.path.isfile(update_path))

    checksum = None
    if download_available:
        try:
            checksum = _file_sha256(update_path)
        except Exception:
            download_available = False

    return jsonify({
        "latest_version": latest,
        "download_available": download_available,
        "checksum_sha256": checksum,
        "changelog": os.getenv("AGENT_CHANGELOG", ""),
    }), 200


# ── Agent endpoints (Agent Bearer token) ─────────────────────────────────────

@update_bp.route("/check", methods=["GET"])
def agent_check():
    """Agent checks if an update is available."""
    if not _any_valid_agent_token():
        return jsonify({"error": "Unauthorized"}), 401

    current = request.args.get("version", "").strip()
    latest = _get_latest_version()
    update_path = _get_update_path()
    download_available = bool(update_path and os.path.isfile(update_path))

    update_available = bool(current and _ver_tuple(latest) > _ver_tuple(current))

    checksum = None
    if download_available and update_available:
        try:
            checksum = _file_sha256(update_path)
        except Exception:
            download_available = False

    download_url = (
        request.host_url.rstrip("/") + "/api/agents/update/download"
        if download_available and update_available else None
    )

    logger.info("Update check: current=%s latest=%s update=%s", current, latest, update_available)
    return jsonify({
        "current_version": current,
        "latest_version": latest,
        "update_available": update_available,
        "download_url": download_url,
        "checksum_sha256": checksum,
        "changelog": os.getenv("AGENT_CHANGELOG", ""),
    }), 200


@update_bp.route("/download", methods=["GET"])
def agent_download():
    """Stream the agent update zip to the requesting agent."""
    if not _any_valid_agent_token():
        return jsonify({"error": "Unauthorized"}), 401

    update_path = _get_update_path()
    if not update_path or not os.path.isfile(update_path):
        return jsonify({"error": "No update package available — set AGENT_UPDATE_PATH in .env"}), 503

    file_size = os.path.getsize(update_path)

    def _stream():
        with open(update_path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                yield chunk

    logger.info("Serving agent update package: %s (%d bytes)", update_path, file_size)
    return Response(
        stream_with_context(_stream()),
        mimetype="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="agent_update.zip"',
            "Content-Length": str(file_size),
        },
    )
