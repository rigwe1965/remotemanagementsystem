"""Licence status for this deployment — admin and superadmin only.

GET /api/admin/licence/status tells the admin screen whether a licence is being enforced, what it covers, how much is in use and
what to say about it. It never returns the licence text or its signature. When ``LICENCE_ENFORCEMENT`` is not ``1`` it answers
``{"enforced": false}`` and nothing else (see utils/licence.py).
"""
from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required

from utils import licence
from utils.auth_decorators import require_role

licence_bp = Blueprint("licence", __name__)


@licence_bp.route("/status", methods=["GET"])
@jwt_required()
def licence_status():
    err = require_role("admin")
    if err:
        return err
    return jsonify(licence.status())
