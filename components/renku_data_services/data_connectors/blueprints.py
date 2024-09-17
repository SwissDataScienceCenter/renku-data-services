"""Data connectors blueprint."""

from dataclasses import dataclass
from typing import Any

from sanic import Request
from sanic.response import HTTPResponse, JSONResponse
from sanic_ext import validate
from ulid import ULID

from renku_data_services import base_models
from renku_data_services.base_api.auth import (
    authenticate,
    only_authenticated,
)
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.etag import extract_if_none_match, if_match_required
from renku_data_services.base_api.misc import validate_query
from renku_data_services.base_api.pagination import PaginationRequest, paginate
from renku_data_services.base_models.validation import validate_and_dump, validated_json
from renku_data_services.data_connectors import apispec, models
from renku_data_services.data_connectors.core import (
    dump_storage_with_sensitive_fields,
    validate_data_connector_patch,
    validate_unsaved_data_connector,
)
from renku_data_services.data_connectors.db import DataConnectorProjectLinkRepository, DataConnectorRepository
from renku_data_services.storage.rclone import RCloneValidator


@dataclass(kw_only=True)
class DataConnectorsBP(CustomBlueprint):
    """Handlers for manipulating data connectors."""

    data_connector_repo: DataConnectorRepository
    data_connector_to_project_link_repo: DataConnectorProjectLinkRepository
    authenticator: base_models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """List data connectors."""

        @authenticate(self.authenticator)
        @validate_query(query=apispec.DataConnectorsGetQuery)
        @paginate
        async def _get_all(
            _: Request,
            user: base_models.APIUser,
            pagination: PaginationRequest,
            query: apispec.DataConnectorsGetQuery,
            validator: RCloneValidator,
        ) -> tuple[list[dict[str, Any]], int]:
            data_connectors, total_num = await self.data_connector_repo.get_data_connectors(
                user=user,
                pagination=pagination,
                namespace=query.namespace,
            )
            return [
                validate_and_dump(
                    apispec.DataConnector,
                    self._dump_data_connector(dc, validator=validator),
                )
                for dc in data_connectors
            ], total_num

        return "/data_connectors", ["GET"], _get_all

    def post(self) -> BlueprintFactoryResponse:
        """Create a new data connector."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.DataConnectorPost)
        async def _post(
            _: Request, user: base_models.APIUser, body: apispec.DataConnectorPost, validator: RCloneValidator
        ) -> JSONResponse:
            data_connector = validate_unsaved_data_connector(body, validator=validator)
            result = await self.data_connector_repo.insert_data_connector(user=user, data_connector=data_connector)
            return validated_json(
                apispec.DataConnector,
                self._dump_data_connector(result, validator=validator),
                status=201,
            )

        return "/data_connectors", ["POST"], _post

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific data connector."""

        @authenticate(self.authenticator)
        @extract_if_none_match
        async def _get_one(
            _: Request, user: base_models.APIUser, data_connector_id: ULID, etag: str | None, validator: RCloneValidator
        ) -> HTTPResponse:
            data_connector = await self.data_connector_repo.get_data_connector(
                user=user, data_connector_id=data_connector_id
            )

            if data_connector.etag == etag:
                return HTTPResponse(status=304)

            headers = {"ETag": data_connector.etag}
            return validated_json(
                apispec.DataConnector,
                self._dump_data_connector(data_connector, validator=validator),
                headers=headers,
            )

        return "/data_connectors/<data_connector_id:ulid>", ["GET"], _get_one

    def get_one_by_slug(self) -> BlueprintFactoryResponse:
        """Get a specific data connector by namespace/entity slug."""

        @authenticate(self.authenticator)
        @extract_if_none_match
        async def _get_one_by_slug(
            _: Request,
            user: base_models.APIUser,
            namespace: str,
            slug: str,
            etag: str | None,
            validator: RCloneValidator,
        ) -> HTTPResponse:
            data_connector = await self.data_connector_repo.get_data_connector_by_slug(
                user=user, namespace=namespace, slug=slug
            )

            if data_connector.etag == etag:
                return HTTPResponse(status=304)

            headers = {"ETag": data_connector.etag}
            return validated_json(
                apispec.DataConnector,
                self._dump_data_connector(data_connector, validator=validator),
                headers=headers,
            )

        return "/namespaces/<namespace>/data_connectors/<slug:renku_slug>", ["GET"], _get_one_by_slug

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a data connector."""

        @authenticate(self.authenticator)
        @only_authenticated
        @if_match_required
        @validate(json=apispec.DataConnectorPatch)
        async def _patch(
            _: Request,
            user: base_models.APIUser,
            data_connector_id: ULID,
            body: apispec.DataConnectorPatch,
            etag: str,
            validator: RCloneValidator,
        ) -> JSONResponse:
            existing_dc = await self.data_connector_repo.get_data_connector(
                user=user, data_connector_id=data_connector_id
            )
            dc_patch = validate_data_connector_patch(existing_dc, body, validator=validator)
            data_connector_update = await self.data_connector_repo.update_data_connector(
                user=user, data_connector_id=data_connector_id, patch=dc_patch, etag=etag
            )

            return validated_json(
                apispec.DataConnector,
                self._dump_data_connector(data_connector_update.new, validator=validator),
            )

        return "/data_connectors/<data_connector_id:ulid>", ["PATCH"], _patch

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a data connector."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete(
            _: Request,
            user: base_models.APIUser,
            data_connector_id: ULID,
        ) -> HTTPResponse:
            await self.data_connector_repo.delete_data_connector(user=user, data_connector_id=data_connector_id)
            return HTTPResponse(status=204)

        return "/data_connectors/<data_connector_id:ulid>", ["DELETE"], _delete

    def get_all_project_links(self) -> BlueprintFactoryResponse:
        """List all links from a given data connector to projects."""

        @authenticate(self.authenticator)
        async def _get_all_project_links(
            _: Request,
            user: base_models.APIUser,
            data_connector_id: ULID,
        ) -> JSONResponse:
            links = await self.data_connector_to_project_link_repo.get_links_from(
                user=user, data_connector_id=data_connector_id
            )
            return validated_json(
                apispec.DataConnectorToProjectLinksList,
                links,
            )

        return "/data_connectors/<data_connector_id:ulid>/project_links", ["GET"], _get_all_project_links

    @staticmethod
    def _dump_data_connector(data_connector: models.DataConnector, validator: RCloneValidator) -> dict[str, Any]:
        """Dumps a data connector for API responses."""
        storage = dump_storage_with_sensitive_fields(data_connector.storage, validator=validator)
        return dict(
            id=data_connector.id,
            name=data_connector.name,
            namespace=data_connector.namespace.slug,
            slug=data_connector.slug,
            storage=storage,
            # secrets=,
            creation_date=data_connector.creation_date,
            created_by=data_connector.created_by,
            visibility=data_connector.visibility.value,
            description=data_connector.description,
            etag=data_connector.etag,
            keywords=data_connector.keywords or [],
        )
