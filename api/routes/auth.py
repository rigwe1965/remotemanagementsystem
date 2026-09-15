import base64
import hashlib
import io
import os
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token, create_refresh_token,
    jwt_required, get_jwt_identity, get_jwt, decode_token
)
import pyotp
from extensions import db, limiter
from models.user import User
from models.audit import AuditLog
from utils.notifications import (
    send_account_locked_email, send_password_reset_email,
    send_login_anomaly_alert,
)
from utils.password import password_error_response
from utils.validation import validate_body
from schemas.auth import (
    LoginSchema, ChangePasswordSchema, ForceChangePasswordSchema,
    MfaEnableSchema, MfaLoginSchema, MfaDisableSchema,
    PasswordResetRequestSchema, PasswordResetConfirmSchema,
)

# Short-lived JWT purpose claims
_MFA_PENDING = "mfa_pending"
_PASSWORD_RESET = "password_reset"
_PASSWORD_EXPIRY_DAYS = 90

auth_bp = Blueprint("auth", __name__)


def _audit(action, user_id=None, payload=None):
    log = AuditLog(
        user_id=user_id,
        action=action,
        resource_type="user",
        ip_address=request.remote_addr,
        user_agent=request.headers.get("User-Agent", "")[:500],
        payload=payload,
    )
    db.session.add(log)


def _device_fp() -> str:
    """Deterministic device fingerprint from User-Agent + Accept-Language."""
    ua = request.headers.get("User-Agent", "")
    lang = request.headers.get("Accept-Language", "")
    return hashlib.sha256(f"{ua}|{lang}".encode()).hexdigest()[:32]


def _track_session(user, refresh_token: str):
    """Upsert one session record per user+device. Invalidates previous session on same device."""
    from models.user_session import UserSession
    fp = _device_fp()
    try:
        jti = decode_token(refresh_token)["jti"]
    except Exception:
        return
    UserSession.query.filter_by(user_id=user.id, device_fp=fp).delete()
    db.session.add(UserSession(user_id=user.id, device_fp=fp, refresh_jti=jti))


def _check_new_ip(user):
    """Record login IP. Alert admin + user if IP is unrecognised (not first login)."""
    ip = request.remote_addr or ""
    if not ip:
        return
    known = list(user.known_ips or [])
    if ip not in known:
        if known:  # skip alert on very first login
            admin_emails = [
                u.email for u in User.query.filter(
                    User.role == "admin", User.is_active == True
                ).all()
            ]
            send_login_anomaly_alert(user.email, ip, admin_emails)
        known = ([ip] + known)[:10]
        user.known_ips = known


def _check_password_expiry(user):
    """Flag must_change_password if password is 90+ days old."""
    if user.password_changed_at and user.role != "superadmin":
        changed_at = user.password_changed_at
        if changed_at.tzinfo is None:
            changed_at = changed_at.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - changed_at
        if age.days >= _PASSWORD_EXPIRY_DAYS:
            user.must_change_password = True


@auth_bp.route("/login", methods=["POST"])
@limiter.limit("5 per minute")
@validate_body(LoginSchema)
def login():
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    user = User.query.filter_by(email=email, is_active=True).first()
    if not user:
        _audit("login_failed", payload={"email": email})
        db.session.commit()
        return jsonify({"error": "Invalid credentials"}), 401

    # Auto-unlock if lockout window has expired
    if user.is_locked and user.locked_until:
        locked_until = user.locked_until
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if locked_until <= datetime.now(timezone.utc):
            user.is_locked = False
            user.locked_until = None
            user.failed_login_attempts = 0
            db.session.commit()

    # Reject if account still locked
    if user.is_locked:
        _audit("login_blocked_locked", user_id=user.id, payload={"email": email})
        db.session.commit()
        return jsonify({
            "error": "account_locked",
            "locked_until": user.locked_until.isoformat() if user.locked_until else None,
        }), 423

    if not user.check_password(password):
        _audit("login_failed", user_id=user.id, payload={"email": email})
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= 3:
            user.is_locked = True
            user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=5)
            db.session.commit()
            admin_emails = [
                u.email for u in User.query.filter(
                    User.role.in_(["admin", "superadmin"]), User.is_active == True,
                    User.email != user.email,
                ).all()
            ]
            send_account_locked_email(user.email, admin_emails)
            return jsonify({
                "error": "account_locked",
                "locked_until": user.locked_until.isoformat(),
            }), 423
        db.session.commit()
        return jsonify({"error": "Invalid credentials"}), 401

    # Successful login — reset lockout state
    user.failed_login_attempts = 0
    user.is_locked = False
    user.locked_until = None

    # Check password expiry (superadmin exempt)
    _check_password_expiry(user)

    # If MFA is enabled, issue a short-lived pending token — full JWT comes after TOTP
    if user.mfa_enabled and user.mfa_secret:
        db.session.commit()
        mfa_token = create_access_token(
            identity=user.id,
            additional_claims={"purpose": _MFA_PENDING},
            expires_delta=timedelta(minutes=5),
        )
        return jsonify({"status": "mfa_required", "mfa_token": mfa_token}), 200

    user.last_login = datetime.now(timezone.utc)
    _audit("login_success", user_id=user.id)

    access_token = create_access_token(
        identity=user.id,
        additional_claims={"role": user.role, "email": user.email, "customer_id": user.customer_id}
    )
    refresh_token = create_refresh_token(identity=user.id)

    _check_new_ip(user)
    _track_session(user, refresh_token)
    db.session.commit()

    return jsonify({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": user.to_dict(),
    }), 200


@auth_bp.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    identity = get_jwt_identity()
    user = db.session.get(User, identity)
    if not user or not user.is_active:
        return jsonify({"error": "User not found"}), 401

    # Per-device session validation
    from models.user_session import UserSession
    jti = get_jwt()["jti"]
    fp = _device_fp()
    session = UserSession.query.filter_by(user_id=identity, device_fp=fp).first()
    if session and session.refresh_jti != jti:
        return jsonify({"error": "Session invalidated — please log in again"}), 401

    access_token = create_access_token(
        identity=user.id,
        additional_claims={"role": user.role, "email": user.email, "customer_id": user.customer_id}
    )
    return jsonify({"access_token": access_token}), 200


@auth_bp.route("/logout", methods=["POST"])
@jwt_required()
def logout():
    """Invalidate the current device session."""
    from models.user_session import UserSession
    identity = get_jwt_identity()
    fp = _device_fp()
    UserSession.query.filter_by(user_id=identity, device_fp=fp).delete()
    db.session.commit()
    return jsonify({"message": "Logged out"}), 200


@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def me():
    identity = get_jwt_identity()
    user = db.session.get(User, identity)
    if not user:
        return jsonify({"error": "User not found"}), 404
    return jsonify(user.to_dict()), 200


@auth_bp.route("/me/password", methods=["PUT"])
@jwt_required()
@validate_body(ChangePasswordSchema)
def change_password():
    identity = get_jwt_identity()
    user = db.session.get(User, identity)
    data = request.get_json(silent=True) or {}

    if not user.check_password(data.get("current_password", "")):
        return jsonify({"error": "Current password incorrect"}), 400

    new_pw = data.get("new_password", "")
    errors, msg = password_error_response(new_pw)
    if errors:
        return jsonify({"error": msg}), 400

    user.set_password(new_pw)
    user.must_change_password = False
    user.password_changed_at = datetime.now(timezone.utc)
    _audit("password_changed", user_id=user.id)
    db.session.commit()
    return jsonify({"message": "Password updated"}), 200


@auth_bp.route("/me/force-change-password", methods=["POST"])
@jwt_required()
@validate_body(ForceChangePasswordSchema)
def force_change_password():
    """Used on forced first-login password change — no current password required."""
    identity = get_jwt_identity()
    user = db.session.get(User, identity)
    if not user:
        return jsonify({"error": "User not found"}), 404
    if not user.must_change_password:
        return jsonify({"error": "Password change not required"}), 403

    data = request.get_json(silent=True) or {}
    new_pw = data.get("new_password", "")
    errors, msg = password_error_response(new_pw)
    if errors:
        return jsonify({"error": msg}), 400

    user.set_password(new_pw)
    user.must_change_password = False
    user.password_changed_at = datetime.now(timezone.utc)
    _audit("force_password_changed", user_id=user.id)
    db.session.commit()
    return jsonify({"message": "Password updated"}), 200


# ── MFA endpoints ────────────────────────────────────────────────────────────

@auth_bp.route("/mfa/setup", methods=["POST"])
@jwt_required()
def mfa_setup():
    """Generate a new TOTP secret for the current user. Returns QR code URI.
    User must call /mfa/enable with a valid code to activate MFA."""
    identity = get_jwt_identity()
    user = db.session.get(User, identity)
    if not user:
        return jsonify({"error": "User not found"}), 404

    secret = pyotp.random_base32()
    user.mfa_secret = secret
    db.session.commit()

    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(
        name=user.email, issuer_name="RMM System"
    )
    return jsonify({
        "secret": secret,
        "provisioning_uri": provisioning_uri,
        "message": "Scan the QR code with your authenticator app, then call /mfa/enable with a valid code.",
    }), 200


@auth_bp.route("/mfa/enable", methods=["POST"])
@jwt_required()
@validate_body(MfaEnableSchema)
def mfa_enable():
    """Verify TOTP code and activate MFA on the account."""
    identity = get_jwt_identity()
    user = db.session.get(User, identity)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json(silent=True) or {}
    code = str(data.get("code", "")).strip()
    if not code:
        return jsonify({"error": "TOTP code required"}), 400

    if not user.mfa_secret:
        return jsonify({"error": "Call /mfa/setup first"}), 400

    totp = pyotp.TOTP(user.mfa_secret)
    if not totp.verify(code, valid_window=1):
        return jsonify({"error": "Invalid or expired TOTP code"}), 401

    user.mfa_enabled = True
    _audit("mfa_enabled", user_id=user.id)
    db.session.commit()
    return jsonify({"message": "MFA enabled successfully"}), 200


@auth_bp.route("/mfa/login", methods=["POST"])
@limiter.limit("10 per minute")
@validate_body(MfaLoginSchema)
def mfa_login():
    """Second step of MFA login. Accepts mfa_token + TOTP code, returns full JWT."""
    data = request.get_json(silent=True) or {}
    mfa_token = data.get("mfa_token", "")
    code = str(data.get("code", "")).strip()

    if not mfa_token or not code:
        return jsonify({"error": "mfa_token and code required"}), 400

    try:
        decoded = decode_token(mfa_token)
    except Exception:
        return jsonify({"error": "Invalid or expired MFA token"}), 401

    if decoded.get("purpose") != _MFA_PENDING:
        return jsonify({"error": "Invalid token type"}), 401

    user_id = decoded.get("sub")
    user = db.session.get(User, user_id)
    if not user or not user.is_active or not user.mfa_secret:
        return jsonify({"error": "User not found or MFA not configured"}), 401

    totp = pyotp.TOTP(user.mfa_secret)
    if not totp.verify(code, valid_window=1):
        _audit("mfa_failed", user_id=user.id)
        db.session.commit()
        return jsonify({"error": "Invalid or expired TOTP code"}), 401

    user.last_login = datetime.now(timezone.utc)
    _check_password_expiry(user)
    _audit("login_success", user_id=user.id)

    access_token = create_access_token(
        identity=user.id,
        additional_claims={"role": user.role, "email": user.email}
    )
    refresh_token = create_refresh_token(identity=user.id)

    _check_new_ip(user)
    _track_session(user, refresh_token)
    db.session.commit()

    return jsonify({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": user.to_dict(),
    }), 200


@auth_bp.route("/mfa/disable", methods=["POST"])
@jwt_required()
@validate_body(MfaDisableSchema)
def mfa_disable():
    """Disable MFA. Requires current password for confirmation."""
    identity = get_jwt_identity()
    user = db.session.get(User, identity)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json(silent=True) or {}
    if not user.check_password(data.get("password", "")):
        return jsonify({"error": "Password confirmation required"}), 401

    user.mfa_enabled = False
    user.mfa_secret = None
    _audit("mfa_disabled", user_id=user.id)
    db.session.commit()
    return jsonify({"message": "MFA disabled"}), 200


@auth_bp.route("/me/avatar", methods=["PUT"])
@jwt_required()
def upload_avatar():
    """Upload or replace profile avatar. Accepts multipart/form-data with 'file' field."""
    from PIL import Image

    identity = get_jwt_identity()
    user = db.session.get(User, identity)
    if not user:
        return jsonify({"error": "User not found"}), 404

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    f = request.files["file"]
    if f.content_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
        return jsonify({"error": "Unsupported image type. Use JPEG, PNG, GIF, or WebP."}), 400

    raw = f.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        return jsonify({"error": "Image must be under 2 MB"}), 400

    try:
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
        img.thumbnail((200, 200), Image.LANCZOS)
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        bg = bg.convert("RGB")
        buf = io.BytesIO()
        bg.save(buf, format="PNG", optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        user.avatar_data = f"data:image/png;base64,{b64}"
    except Exception as exc:
        return jsonify({"error": f"Image processing failed: {exc}"}), 422

    _audit("avatar_updated", user_id=user.id)
    db.session.commit()
    return jsonify({"message": "Avatar updated", "user": user.to_dict()}), 200


@auth_bp.route("/me/avatar", methods=["DELETE"])
@jwt_required()
def delete_avatar():
    """Remove the current user's avatar."""
    identity = get_jwt_identity()
    user = db.session.get(User, identity)
    if not user:
        return jsonify({"error": "User not found"}), 404

    user.avatar_data = None
    _audit("avatar_removed", user_id=user.id)
    db.session.commit()
    return jsonify({"message": "Avatar removed", "user": user.to_dict()}), 200


# ── Password reset endpoints ──────────────────────────────────────────────────

@auth_bp.route("/password-reset/request", methods=["POST"])
@limiter.limit("5 per minute")
@validate_body(PasswordResetRequestSchema)
def password_reset_request():
    """Request a password reset link. Always returns 200 to prevent email enumeration."""
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"message": "If that email is registered, a reset link has been sent."}), 200

    user = User.query.filter_by(email=email, is_active=True).first()
    if user:
        reset_token = create_access_token(
            identity=user.id,
            additional_claims={"purpose": _PASSWORD_RESET},
            expires_delta=timedelta(hours=1),
        )
        dashboard_url = os.getenv("DASHBOARD_URL", "http://localhost:8501")
        reset_url = f"{dashboard_url}/?reset_token={reset_token}"
        send_password_reset_email(user.email, reset_url)
        _audit("password_reset_requested", user_id=user.id, payload={"email": email})
        db.session.commit()

    return jsonify({"message": "If that email is registered, a reset link has been sent."}), 200


@auth_bp.route("/password-reset/confirm", methods=["POST"])
@validate_body(PasswordResetConfirmSchema)
def password_reset_confirm():
    """Confirm a password reset using the token from the reset link."""
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    new_password = data.get("new_password", "")

    if not token or not new_password:
        return jsonify({"error": "token and new_password are required"}), 400

    errors, msg = password_error_response(new_password)
    if errors:
        return jsonify({"error": msg}), 400

    try:
        decoded = decode_token(token)
    except Exception:
        return jsonify({"error": "Invalid or expired reset link"}), 400

    if decoded.get("purpose") != _PASSWORD_RESET:
        return jsonify({"error": "Invalid token type"}), 400

    user_id = decoded.get("sub")
    user = db.session.get(User, user_id)
    if not user or not user.is_active:
        return jsonify({"error": "User not found"}), 404

    user.set_password(new_password)
    user.must_change_password = False
    user.password_changed_at = datetime.now(timezone.utc)
    user.is_locked = False
    user.locked_until = None
    user.failed_login_attempts = 0
    _audit("password_reset_completed", user_id=user.id)
    db.session.commit()
    return jsonify({"message": "Password reset successful. You can now log in."}), 200
