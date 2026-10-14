"""Repositories blueprint."""

from dataclasses import dataclass

from sanic import HTTPResponse, Request
from sanic.response import JSONResponse
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.base_api.auth import authenticate
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.etag import extract_if_none_match
from renku_data_services.base_api.misc import validate_query
from renku_data_services.base_models.validation import validated_json
from renku_data_services.errors.errors import ValidationError
from renku_data_services.repositories import apispec, models
from renku_data_services.repositories.db import GitRepositoriesRepository
from renku_data_services.repositories.git_url import GitUrlError


@dataclass(kw_only=True)
class RepositoriesBP(CustomBlueprint):
    """Handlers for using OAuth2 connections."""

    git_repositories_repo: GitRepositoriesRepository
    authenticator: base_models.Authenticator
    internal_gitlab_authenticator: base_models.Authenticator

    def get_one_repository(self) -> BlueprintFactoryResponse:
        """Get the metadata available about a repository."""

        @authenticate(self.authenticator)
        @extract_if_none_match
        async def _get_one_repository(
            req: Request,
            user: base_models.APIUser,
            etag: str | None,
        ) -> JSONResponse | HTTPResponse:
            query_args: dict[str, str] = req.get_args() or {}
            repository_url = query_args.get("url")
            if repository_url is None:
                raise ValidationError(message="A repository url is required")

            result = await self.git_repositories_repo.get_repository(
                repository_url=repository_url,
                user=user,
                etag=etag,
            )
            if result.metadata == "Unmodified":
                return HTTPResponse(status=304)
            headers = {"ETag": result.metadata.etag} if result.metadata and result.metadata.etag else None
            body = self._make_result(result)
            return validated_json(apispec.RepositoryProviderData, body, headers=headers)

        return "/repository", ["GET"], _get_one_repository

    def _make_result(self, r: models.RepositoryDataResult) -> apispec.RepositoryProviderData:
        status = apispec.Status.unknown
        if r.is_success:
            status = apispec.Status.valid
        if r.is_error:
            status = apispec.Status.invalid

        conn = (
            apispec.ProviderConnection(
                id=str(r.connection.id), provider_id=r.connection.provider_id, status=r.connection.status
            )
            if r.connection
            else None
        )
        prov = apispec.ProviderData(id=r.provider.id, name=r.provider.name, url=r.provider.url) if r.provider else None
        meta = (
            apispec.Metadata(
                git_url=r.metadata.git_url,
                web_url=r.metadata.web_url,
                pull_permission=r.metadata.pull_permission,
                push_permission=r.metadata.push_permission,
                visibility=apispec.RepositoryVisibility(r.metadata.visibility.value),
            )
            if r.metadata and r.metadata != "Unmodified"
            else None
        )
        error_code: apispec.ErrorCode | None
        match r.error:
            case GitUrlError() as e:
                error_code = apispec.ErrorCode[e.value]
            case models.RepositoryMetadataError() as e:
                error_code = apispec.ErrorCode[e.value]
            case None:
                error_code = None

        return apispec.RepositoryProviderData(
            status=status, connection=conn, provider=prov, metadata=meta, error_code=error_code
        )

    def get_repository_permissions(self) -> BlueprintFactoryResponse:
        """Get detailed permissions from a repository hosted on GitHub."""

        # @authenticate(self.authenticator)
        # @validate_query(query=apispec.ResourceClassParams)
        # @validate_db_ids
        # async def _get_all(
        #     request: Request, user: base_models.APIUser, resource_pool_id: int, query: apispec.ResourceClassParams
        # ) -> HTTPResponse:
        #     res = await self.repo.get_classes(api_user=user, resource_pool_id=resource_pool_id, name=query.name)
        #     return validated_json(apispec.ResourceClassesWithIdResponse, res)

        # return "/resource_pools/<resource_pool_id>/classes", ["GET"], _get_all

        @authenticate(self.authenticator)
        @validate_query(query=apispec.RepositoryPermissionsGetParametersQuery)
        @extract_if_none_match
        async def _get_repository_permissions(
            req: Request,
            user: base_models.APIUser,
            query: apispec.RepositoryPermissionsGetParametersQuery,
            etag: str | None,
        ) -> JSONResponse | HTTPResponse:
            repository_url = query.repository_permissions_params.url
            connection_id_str = query.repository_permissions_params.connection_id

            try:
                connection_id = ULID.from_str(connection_id_str)
            except ValueError as e:
                raise errors.ValidationError(message=f"Connection ID {connection_id_str} must be a valid ULID.") from e

            result = await self.git_repositories_repo.get_repository_permissions(
                repository_url=repository_url, connection_id=connection_id, user=user, etag=etag
            )
            if result.permissions == "Unmodified":
                return HTTPResponse(status=304)

            # TODO
            # headers = {"ETag": result.metadata.etag} if result.metadata and result.metadata.etag else None

            raise NotImplementedError()

        return "/repository/permissions", ["GET"], _get_repository_permissions
