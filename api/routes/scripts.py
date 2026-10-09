from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from extensions import db, limiter
from models.script import Script, ScriptRun
from utils.validation import validate_body
from schemas.scripts import ScriptCreateSchema, ScriptUpdateSchema, RunScriptSchema
from utils.auth_decorators import require_role as _require_role
from utils.pagination import paginated_response

scripts_bp = Blueprint("scripts", __name__)

ALLOWED_TYPES = {"bat", "ps1", "py"}
MAX_SCRIPT_SIZE = 512 * 1024  # 512KB


@scripts_bp.route("/", methods=["GET"])
@jwt_required()
def list_scripts():
    err = _require_role("admin", "technician", "viewer")
    if err:
        return err
    is_builtin = request.args.get("is_builtin")
    file_type = request.args.get("file_type")

    query = Script.query
    if is_builtin is not None:
        query = query.filter_by(is_builtin=is_builtin.lower() == "true")
    if file_type:
        query = query.filter_by(file_type=file_type)

    scripts = query.order_by(Script.name).all()
    return jsonify([s.to_dict(include_content=False) for s in scripts]), 200


@scripts_bp.route("/", methods=["POST"])
@jwt_required()
@validate_body(ScriptCreateSchema)
def create_script():
    err = _require_role("admin", "technician")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    file_type = data.get("file_type", "").strip().lower()
    content = data.get("content", "")

    if not name or not file_type or not content:
        return jsonify({"error": "name, file_type, content required"}), 400
    if file_type not in ALLOWED_TYPES:
        return jsonify({"error": f"file_type must be one of: {', '.join(ALLOWED_TYPES)}"}), 400
    if len(content.encode("utf-8")) > MAX_SCRIPT_SIZE:
        return jsonify({"error": "Script exceeds 512KB limit"}), 400

    script = Script(
        name=name,
        description=data.get("description"),
        file_type=file_type,
        content=content,
        uploaded_by=get_jwt_identity(),
        os_target=data.get("os_target", "windows"),
        tags=data.get("tags", []),
    )
    db.session.add(script)
    db.session.commit()
    return jsonify(script.to_dict()), 201


@scripts_bp.route("/<script_id>", methods=["GET"])
@jwt_required()
def get_script(script_id):
    err = _require_role("admin", "technician", "viewer")
    if err:
        return err
    script = db.get_or_404(Script, script_id)
    return jsonify(script.to_dict(include_content=True)), 200


@scripts_bp.route("/<script_id>", methods=["PUT"])
@jwt_required()
@validate_body(ScriptUpdateSchema)
def update_script(script_id):
    err = _require_role("admin", "technician")
    if err:
        return err
    script = db.get_or_404(Script, script_id)
    if script.is_builtin:
        return jsonify({"error": "Cannot edit built-in scripts"}), 400
    data = request.get_json(silent=True) or {}
    for field in ["name", "description", "content", "tags"]:
        if field in data:
            setattr(script, field, data[field])
    db.session.commit()
    return jsonify(script.to_dict()), 200


@scripts_bp.route("/<script_id>", methods=["DELETE"])
@jwt_required()
def delete_script(script_id):
    err = _require_role("admin", "technician")
    if err:
        return err
    script = db.get_or_404(Script, script_id)
    if script.is_builtin:
        return jsonify({"error": "Cannot delete built-in scripts"}), 400
    db.session.delete(script)
    db.session.commit()
    return jsonify({"message": "Script deleted"}), 200


@scripts_bp.route("/<script_id>/run", methods=["POST"])
@jwt_required()
@limiter.limit("5 per minute")
@validate_body(RunScriptSchema)
def run_script(script_id):
    from services.script_service import run_script_service
    claims = get_jwt()
    uid = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    result, err = run_script_service(
        uid, claims.get("role"), claims.get("customer_id"),
        script_id, data.get("device_ids", []), data.get("timeout_seconds", 300),
    )
    if err:
        return jsonify({"error": err[0]}), err[1]
    return jsonify(result), 202


@scripts_bp.route("/runs", methods=["GET"])
@jwt_required()
def list_runs():
    err = _require_role("admin", "technician", "viewer")
    if err:
        return err
    device_id = request.args.get("device_id")
    script_id = request.args.get("script_id")
    status = request.args.get("status")

    query = ScriptRun.query
    if device_id:
        query = query.filter_by(device_id=device_id)
    if script_id:
        query = query.filter_by(script_id=script_id)
    if status:
        query = query.filter_by(status=status)

    return paginated_response(query, lambda r: r.to_dict(), order_by=ScriptRun.triggered_at.desc())


@scripts_bp.route("/runs/<run_id>", methods=["GET"])
@jwt_required()
def get_run(run_id):
    err = _require_role("admin", "technician", "viewer")
    if err:
        return err
    run = db.get_or_404(ScriptRun, run_id)
    return jsonify(run.to_dict()), 200
