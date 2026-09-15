"""
Admin routes — user management, department management, and system config (admin-only).
"""
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from extensions import db
from models.user import User
from models.department import Department
from models.audit import AuditLog
from utils.password import password_error_response
from utils.validation import validate_body
from schemas.admin import (
    CreateUserSchema, UpdateUserSchema,
    DepartmentCreateSchema, DepartmentUpdateSchema,
)

admin_bp = Blueprint("admin", __name__)

_VALID_STAFF_ROLES = ("admin", "technician", "viewer", "client")


def _require_admin():
    uid = get_jwt_identity()
    user = db.session.get(User, uid)
    if not user or user.role not in ("admin", "superadmin"):
        return None, jsonify({"error": "Admin access required"}), 403
    return user, None, None


def _audit(action, admin_id, resource_id=None, payload=None):
    log = AuditLog(
        user_id=admin_id,
        action=action,
        resource_type="user",
        resource_id=resource_id,
        ip_address=request.remote_addr,
        user_agent=request.headers.get("User-Agent", "")[:500],
        payload=payload,
    )
    db.session.add(log)


# ── Users ─────────────────────────────────────────────────────────────────────

@admin_bp.route("/users", methods=["GET"])
@jwt_required()
def list_users():
    admin, err, code = _require_admin()
    if err:
        return err, code

    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 200)
    include_inactive = request.args.get("include_inactive", "false").lower() == "true"
    query = User.query if include_inactive else User.query.filter_by(is_active=True)
    query = query.filter(~User.email.like("__deleted__%"))
    paginated = query.order_by(User.created_at.desc()).paginate(page=page, per_page=per_page)
    return jsonify({"users": [u.to_dict() for u in paginated.items], "total": paginated.total, "page": page})


@admin_bp.route("/users", methods=["POST"])
@jwt_required()
@validate_body(CreateUserSchema)
def create_user():
    admin, err, code = _require_admin()
    if err:
        return err, code

    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    full_name = (data.get("full_name") or "").strip()
    role = (data.get("role") or "technician").strip().lower()
    password = data.get("password") or ""

    if not email or not full_name or not password:
        return jsonify({"error": "email, full_name, and password are required"}), 400
    if role not in _VALID_STAFF_ROLES:
        return jsonify({"error": f"role must be one of: {', '.join(_VALID_STAFF_ROLES)}"}), 400
    if role == "client" and not data.get("customer_id"):
        return jsonify({"error": "customer_id is required for client accounts"}), 400
    errors, msg = password_error_response(password)
    if errors:
        return jsonify({"error": msg}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already in use"}), 409

    must_change = bool(data.get("must_change_password", False))
    user = User(
        email=email,
        full_name=full_name,
        role=role,
        must_change_password=must_change,
        department_id=data.get("department_id") or None,
        customer_id=data.get("customer_id") or None,
    )
    user.set_password(password)
    db.session.add(user)
    _audit("CREATE", admin.id, payload={"email": email, "role": role})
    db.session.commit()
    return jsonify(user.to_dict()), 201


@admin_bp.route("/users/<user_id>", methods=["PUT"])
@jwt_required()
@validate_body(UpdateUserSchema)
def update_user(user_id):
    admin, err, code = _require_admin()
    if err:
        return err, code

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    if user.role == "superadmin":
        return jsonify({"error": "Superadmin account cannot be modified via the API. Use reset_superadmin.py CLI."}), 403

    data = request.get_json(silent=True) or {}
    if "full_name" in data:
        user.full_name = data["full_name"].strip()
    if "role" in data:
        role = data["role"].strip().lower()
        if role not in _VALID_STAFF_ROLES:
            return jsonify({"error": f"role must be one of: {', '.join(_VALID_STAFF_ROLES)}"}), 400
        user.role = role
    if "department_id" in data:
        user.department_id = data["department_id"] or None
    if "customer_id" in data:
        user.customer_id = data["customer_id"] or None
    if "is_active" in data:
        user.is_active = bool(data["is_active"])
    if data.get("password"):
        errors, msg = password_error_response(data["password"])
        if errors:
            return jsonify({"error": msg}), 400
        user.set_password(data["password"])
    if "must_change_password" in data:
        user.must_change_password = bool(data["must_change_password"])

    _audit("UPDATE", admin.id, resource_id=user_id, payload={"email": user.email})
    db.session.commit()
    return jsonify(user.to_dict())


@admin_bp.route("/users/<user_id>", methods=["DELETE"])
@jwt_required()
def delete_user(user_id):
    admin, err, code = _require_admin()
    if err:
        return err, code

    if user_id == admin.id:
        return jsonify({"error": "Cannot delete your own account"}), 400

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    if user.role == "superadmin":
        return jsonify({"error": "Superadmin account cannot be deleted"}), 403

    _audit("DELETE", admin.id, resource_id=user_id, payload={"email": user.email})
    user.is_active = False
    user.email = f"__deleted__{user.id}@rmm.local"
    db.session.commit()
    return jsonify({"message": "User deleted"})


@admin_bp.route("/users/<user_id>/deactivate", methods=["POST"])
@jwt_required()
def deactivate_user(user_id):
    admin, err, code = _require_admin()
    if err:
        return err, code

    if user_id == admin.id:
        return jsonify({"error": "Cannot deactivate your own account"}), 400

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    if user.role == "superadmin":
        return jsonify({"error": "Superadmin account cannot be deactivated"}), 403
    if not user.is_active:
        return jsonify({"error": "Account is already inactive"}), 400

    user.is_active = False
    _audit("DEACTIVATE", admin.id, resource_id=user_id, payload={"email": user.email})
    db.session.commit()
    return jsonify({"message": "Account deactivated", "user": user.to_dict()})


@admin_bp.route("/users/<user_id>/reactivate", methods=["POST"])
@jwt_required()
def reactivate_user(user_id):
    admin, err, code = _require_admin()
    if err:
        return err, code

    user = User.query.filter_by(id=user_id).first()
    if not user:
        return jsonify({"error": "User not found"}), 404
    if user.role == "superadmin":
        return jsonify({"error": "Superadmin account cannot be modified via the API"}), 403
    if user.is_active:
        return jsonify({"error": "Account is already active"}), 400

    user.is_active = True
    _audit("REACTIVATE", admin.id, resource_id=user_id, payload={"email": user.email})
    db.session.commit()
    return jsonify({"message": "Account reactivated", "user": user.to_dict()})


@admin_bp.route("/users/<user_id>/unlock", methods=["POST"])
@jwt_required()
def unlock_user(user_id):
    admin, err, code = _require_admin()
    if err:
        return err, code

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    if user.role == "superadmin":
        return jsonify({"error": "Superadmin account cannot be modified via the API"}), 403

    user.is_locked = False
    user.locked_until = None
    user.failed_login_attempts = 0
    _audit("UNLOCK", admin.id, resource_id=user_id, payload={"email": user.email})
    db.session.commit()
    return jsonify({"message": "Account unlocked", "user": user.to_dict()})


# ── Departments ────────────────────────────────────────────────────────────────

@admin_bp.route("/departments", methods=["GET"])
@jwt_required()
def list_departments():
    admin, err, code = _require_admin()
    if err:
        return err, code
    depts = Department.query.order_by(Department.name).all()
    return jsonify({"departments": [d.to_dict(include_members=True) for d in depts]})


@admin_bp.route("/departments", methods=["POST"])
@jwt_required()
@validate_body(DepartmentCreateSchema)
def create_department():
    admin, err, code = _require_admin()
    if err:
        return err, code

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    if Department.query.filter_by(name=name).first():
        return jsonify({"error": "Department name already in use"}), 409

    dept = Department(
        name=name,
        description=data.get("description"),
        color=data.get("color", "#407E3C"),
    )
    db.session.add(dept)
    db.session.commit()
    return jsonify(dept.to_dict(include_members=True)), 201


@admin_bp.route("/departments/<dept_id>", methods=["PUT"])
@jwt_required()
@validate_body(DepartmentUpdateSchema)
def update_department(dept_id):
    admin, err, code = _require_admin()
    if err:
        return err, code

    dept = db.get_or_404(Department, dept_id)
    data = request.get_json(silent=True) or {}

    if "name" in data:
        new_name = data["name"].strip()
        conflict = Department.query.filter(
            Department.name == new_name, Department.id != dept_id
        ).first()
        if conflict:
            return jsonify({"error": "Department name already in use"}), 409
        dept.name = new_name
    if "description" in data:
        dept.description = data["description"]
    if "color" in data:
        dept.color = data["color"]

    db.session.commit()
    return jsonify(dept.to_dict(include_members=True))


@admin_bp.route("/departments/<dept_id>", methods=["DELETE"])
@jwt_required()
def delete_department(dept_id):
    admin, err, code = _require_admin()
    if err:
        return err, code

    dept = db.get_or_404(Department, dept_id)
    if dept.name == "Help Desk":
        return jsonify({"error": "The Help Desk department cannot be deleted"}), 400

    # Unlink members before deleting
    User.query.filter_by(department_id=dept_id).update({"department_id": None})
    db.session.delete(dept)
    db.session.commit()
    return jsonify({"message": "Department deleted"})


@admin_bp.route("/departments/<dept_id>/members", methods=["POST"])
@jwt_required()
def set_department_member(dept_id):
    """Assign or remove a user from a department. Body: {user_id, action: 'add'|'remove'}"""
    admin, err, code = _require_admin()
    if err:
        return err, code

    db.get_or_404(Department, dept_id)
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    action = data.get("action", "add")

    if not user_id:
        return jsonify({"error": "user_id required"}), 400

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    user.department_id = dept_id if action == "add" else None
    db.session.commit()
    return jsonify({"message": f"User {action}ed", "user": user.to_dict()})


# ── System ─────────────────────────────────────────────────────────────────────

@admin_bp.route("/org-token", methods=["GET"])
@jwt_required()
def get_org_token():
    _, err, code = _require_admin()
    if err:
        return err, code
    token = current_app.config.get("ORG_REGISTRATION_TOKEN", "")
    return jsonify({"org_token": token})


@admin_bp.route("/users/<user_id>/gdpr-export", methods=["GET"])
@jwt_required()
def gdpr_export_user(user_id):
    """Export all personal data associated with a user account (GDPR Art. 20)."""
    admin, err, code = _require_admin()
    if err:
        return err, code

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    from models.ticket import TicketComment
    from models.audit import AuditLog as AL

    audit_logs = AL.query.filter_by(user_id=user_id).order_by(AL.created_at).limit(1000).all()
    comments = TicketComment.query.filter_by(author_id=user_id).order_by(TicketComment.created_at).limit(1000).all()

    export = {
        "exported_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "user": user.to_dict(),
        "audit_log": [a.to_dict() for a in audit_logs],
        "ticket_comments": [c.to_dict() for c in comments],
    }
    _audit("GDPR_EXPORT", admin.id, resource_id=user_id, payload={"exported_by": admin.email})
    db.session.commit()
    return jsonify(export), 200


@admin_bp.route("/users/<user_id>/gdpr-delete", methods=["DELETE"])
@jwt_required()
def gdpr_delete_user(user_id):
    """Anonymize all personal data for a user account (GDPR Art. 17 — right to erasure)."""
    admin, err, code = _require_admin()
    if err:
        return err, code

    if user_id == admin.id:
        return jsonify({"error": "Cannot anonymize your own account"}), 400

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    if user.role == "superadmin":
        return jsonify({"error": "Superadmin account cannot be anonymized"}), 403

    from models.ticket import TicketComment
    from models.audit import AuditLog as AL

    anon_id = user.id[:8]
    original_email = user.email

    # Anonymize PII on the user record
    user.email = f"__anon__{anon_id}@deleted.local"
    user.full_name = f"Deleted User {anon_id}"
    user.password_hash = ""
    user.is_active = False
    user.avatar_data = None

    # Scrub email from ticket comments they authored
    TicketComment.query.filter_by(author_id=user_id).update({
        "author_email": None,
    })

    # Scrub IP addresses from their audit log entries
    AL.query.filter_by(user_id=user_id).update({"ip_address": "0.0.0.0"})

    _audit("GDPR_DELETE", admin.id, resource_id=user_id, payload={"anonymized": original_email})
    db.session.commit()
    return jsonify({"message": f"User data anonymized", "user_id": user_id}), 200


@admin_bp.route("/server_ips", methods=["GET"])
@jwt_required()
def server_ips():
    _, err, code = _require_admin()
    if err:
        return err, code
    import socket
    hostname = socket.gethostname()
    ips = []
    try:
        for info in socket.getaddrinfo(hostname, None):
            ip = info[4][0]
            if not ip.startswith("127.") and ":" not in ip and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    if not ips:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                ips = [s.getsockname()[0]]
        except Exception:
            ips = []
    return jsonify({"hostname": hostname, "lan_ips": ips})
