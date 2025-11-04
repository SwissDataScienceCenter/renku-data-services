"""Notification blueprint."""

from dataclasses import dataclass
from typing import Any

from sanic import HTTPResponse, Request
from sanic.response import JSONResponse
from sanic_ext import validate
from ulid import ulid

import renku_data_services.base_models as base_models

from renku_data_services.base_api.auth import (
    authenticate,
    only_authenticated,
    validate_path_user_id.
)

from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.etag import extract_if_none_match, if_match_required
from renku_data_services.base_api.misc import validate_body_root_model, validate_query
from renku_data_services.base_models.validation import validated_json
from renku_data_services.base_api.pagination import PaginationRequest, paginate

from renku_data_services.errors import errors
from renku_data_services.notifications import apispec

