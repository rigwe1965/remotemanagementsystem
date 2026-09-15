import base64
import io
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from extensions import db
from models.org_settings import OrgSettings
from utils.validation import validate_body
from schemas.org_settings import OrgSettingsSchema

org_settings_bp = Blueprint("org_settings", __name__)


def _require_admin():
    claims = get_jwt()
    if claims.get("role") in ("admin", "superadmin"):
        return None
    return jsonify({"error": "Admin access required"}), 403


@org_settings_bp.route("/org-settings", methods=["GET"])
@jwt_required()
def get_org_settings():
    settings = db.session.get(OrgSettings, 1)
    if not settings:
        settings = OrgSettings(id=1)
        db.session.add(settings)
        db.session.commit()
    return jsonify(settings.to_dict()), 200


@org_settings_bp.route("/org-settings", methods=["PUT"])
@jwt_required()
@validate_body(OrgSettingsSchema)
def update_org_settings():
    err = _require_admin()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    settings = db.session.get(OrgSettings, 1)
    if not settings:
        settings = OrgSettings(id=1)
        db.session.add(settings)

    for field in ["company_name", "company_address", "company_email",
                  "company_phone", "payment_terms", "bank_details", "footer_notes",
                  "app_name", "tagline", "primary_color", "currency", "timezone"]:
        if field in data:
            setattr(settings, field, data[field])

    db.session.commit()
    return jsonify(settings.to_dict()), 200


@org_settings_bp.route("/org-settings/logo", methods=["PUT"])
@jwt_required()
def upload_org_logo():
    err = _require_admin()
    if err:
        return err

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f = request.files["file"]
    content_type = f.content_type or "image/png"
    if not content_type.startswith("image/"):
        return jsonify({"error": "File must be an image"}), 400

    raw = f.read()
    if len(raw) > 2 * 1024 * 1024:
        return jsonify({"error": "Logo must be under 2 MB"}), 400

    try:
        from PIL import Image
        img = Image.open(io.BytesIO(raw))
        max_w = 400
        if img.width > max_w:
            ratio = max_w / img.width
            img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        out = io.BytesIO()
        img.save(out, format="PNG", optimize=True)
        logo_b64 = "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()
    except Exception as e:
        return jsonify({"error": f"Image processing failed: {e}"}), 400

    settings = db.session.get(OrgSettings, 1)
    if not settings:
        settings = OrgSettings(id=1)
        db.session.add(settings)
    settings.logo_data = logo_b64
    db.session.commit()
    return jsonify({"message": "Logo updated", "logo_data": logo_b64}), 200


@org_settings_bp.route("/public/branding", methods=["GET"])
def public_branding():
    """Public endpoint — no auth. Returns white-label branding fields only."""
    settings = db.session.get(OrgSettings, 1)
    if not settings:
        return jsonify({
            "app_name":      "RMM System",
            "tagline":       "Remote Monitoring & Management",
            "primary_color": "#407E3C",
            "logo_data":     None,
        }), 200
    return jsonify({
        "app_name":      settings.app_name or "RMM System",
        "tagline":       settings.tagline or "Remote Monitoring & Management",
        "primary_color": settings.primary_color or "#407E3C",
        "logo_data":     settings.logo_data,
    }), 200


@org_settings_bp.route("/org-settings/logo", methods=["DELETE"])
@jwt_required()
def delete_org_logo():
    err = _require_admin()
    if err:
        return err
    settings = db.session.get(OrgSettings, 1)
    if settings:
        settings.logo_data = None
        db.session.commit()
    return jsonify({"message": "Logo removed"}), 200
