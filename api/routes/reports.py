from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from extensions import db
from models.report import Report

reports_bp = Blueprint("reports", __name__)


@reports_bp.route("/templates", methods=["GET"])
@jwt_required()
def list_templates():
    return jsonify([
        {"type": "patch_summary", "name": "Patch Summary Report"},
        {"type": "device_health", "name": "Device Health Report"},
        {"type": "ticket_summary", "name": "Ticket Summary Report"},
        {"type": "software_inventory", "name": "Software Inventory Report"},
        {"type": "billing", "name": "Billing Report"},
    ]), 200


@reports_bp.route("/", methods=["GET"])
@jwt_required()
def list_reports():
    reports = Report.query.order_by(Report.generated_at.desc()).limit(100).all()
    return jsonify([r.to_dict() for r in reports]), 200


@reports_bp.route("/generate", methods=["POST"])
@jwt_required()
def generate_report():
    data = request.get_json(silent=True) or {}
    if not data.get("template_type"):
        return jsonify({"error": "template_type required"}), 400

    report = Report(
        name=data.get("name", f"{data['template_type']} report"),
        template_type=data["template_type"],
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
    report = db.get_or_404(Report, report_id)
    return jsonify(report.to_dict()), 200
