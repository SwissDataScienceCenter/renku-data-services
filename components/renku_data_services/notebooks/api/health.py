from flask import Blueprint, Response

from .. import config

bp = Blueprint("health_blueprint", __name__)


@bp.route("/health")
def health():
    """Just a health check path."""
    return Response("service running under {}".format(config.SERVICE_PREFIX))
