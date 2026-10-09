from flask import Blueprint, request, jsonify
from utils.auth_decorators import require_role as _require_role
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from extensions import db
from models.report import Report

reports_bp = Blueprint("reports", __name__)

# Admin/superadmin-only report type — same restriction as /api/admin/usage/*,
# since it surfaces the same API/token usage data.
_USAGE_RESTRICTED_TEMPLATES = ("api_usage",)


def _is_admin_or_above() -> bool:
    return get_jwt().get("role") in ("admin", "superadmin")


@reports_bp.route("/templates", methods=["GET"])
@jwt_required()
def list_templates():
    err = _require_role("admin", "technician", "viewer")
    if err:
        return err
    templates = [
        {"type": "patch_summary", "name": "Patch Summary Report"},
        {"type": "device_health", "name": "Device Health Report"},
        {"type": "ticket_summary", "name": "Ticket Summary Report"},
        {"type": "software_inventory", "name": "Software Inventory Report"},
        {"type": "billing", "name": "Billing Report"},
    ]
    if _is_admin_or_above():
        templates.append({"type": "api_usage", "name": "API & Token Usage Report"})
    return jsonify(templates), 200


@reports_bp.route("/", methods=["GET"])
@jwt_required()
def list_reports():
    err = _require_role("admin", "technician", "viewer")
    if err:
        return err
    q = Report.query
    if not _is_admin_or_above():
        q = q.filter(Report.template_type.notin_(_USAGE_RESTRICTED_TEMPLATES))
    reports = q.order_by(Report.generated_at.desc()).limit(100).all()
    return jsonify([r.to_dict() for r in reports]), 200


@reports_bp.route("/generate", methods=["POST"])
@jwt_required()
def generate_report():
    err = _require_role("admin", "technician", "viewer")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    template_type = data.get("template_type")
    if not template_type:
        return jsonify({"error": "template_type required"}), 400
    if template_type in _USAGE_RESTRICTED_TEMPLATES and not _is_admin_or_above():
        return jsonify({"error": "Administrator access required"}), 403

    report = Report(
        name=data.get("name", f"{template_type} report"),
        template_type=template_type,
        customer_id=data.get("customer_id"),
        format=data.get("format", "pdf"),
        parameters=data.get("parameters", {}),
        generated_by=get_jwt_identity(),
    )
    db.session.add(report)
    db.session.commit()
    from tasks.report_tasks import generate_report as gen_task
    gen_task.delay(report.id)
    return jsonify({"message": "Report queued", "report_id": report.id}), 202


@reports_bp.route("/<report_id>", methods=["GET"])
@jwt_required()
def get_report(report_id):
    err = _require_role("admin", "technician", "viewer")
    if err:
        return err
    report = db.get_or_404(Report, report_id)
    if report.template_type in _USAGE_RESTRICTED_TEMPLATES and not _is_admin_or_above():
        return jsonify({"error": "Administrator access required"}), 403
    return jsonify(report.to_dict()), 200
