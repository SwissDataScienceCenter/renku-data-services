from flask import Blueprint, Response

from ..config import config

bp = Blueprint("health_blueprint", __name__)


@bp.route("/health")
def health():
    """Just a health check path."""
    return Response(f"service running under {config.service_prefix}")
