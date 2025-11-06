"""Repositories blueprint."""

from dataclasses import dataclass
from urllib.parse import unquote

from renku_data_services.repositories.git_url import GitUrlError
from sanic import HTTPResponse, Request
from sanic.response import JSONResponse

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.base_api.auth import authenticate_2
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.etag import extract_if_none_match
from renku_data_services.base_models.validation import validated_json
from renku_data_services.repositories import apispec, models
from renku_data_services.repositories.apispec_base import RepositoryParams
from renku_data_services.repositories.db import GitRepositoriesRepository
from renku_data_services.repositories.utils import probe_repository


@dataclass(kw_only=True)
class RepositoriesBP(CustomBlueprint):
    """Handlers for using OAuth2 connections."""

    git_repositories_repo: GitRepositoriesRepository
    authenticator: base_models.Authenticator
    internal_gitlab_authenticator: base_models.Authenticator

    def get_one_repository(self) -> BlueprintFactoryResponse:
        """Get the metadata available about a repository."""

        @authenticate_2(self.authenticator, self.internal_gitlab_authenticator)
        @extract_if_none_match
        async def _get_one_repository(
            _: Request,
            user: base_models.APIUser,
            internal_gitlab_user: base_models.APIUser,
            repository_url: str,
            etag: str | None,
        ) -> JSONResponse | HTTPResponse:
            repository_url = unquote(repository_url)

            result = await self.git_repositories_repo.get_repository(
                repository_url=repository_url,
                user=user,
                etag=etag,
                internal_gitlab_user=internal_gitlab_user,
            )
            if result.metadata == "Unmodified":
                return HTTPResponse(status=304)
            headers = {"ETag": result.metadata.etag} if result.metadata and result.metadata.etag else None
            body = self._make_result(result)
            return validated_json(apispec.RepositoryProviderData, body, headers=headers)

        return "/repositories/<repository_url>", ["GET"], _get_one_repository

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

    def get_one_repository_probe(self) -> BlueprintFactoryResponse:
        """Probe a repository to check if it is publicly available."""

        async def _get_one_repository_probe(_: Request, repository_url: str) -> HTTPResponse:
            repository_url = unquote(repository_url)
            RepositoryParams.model_validate(dict(repository_url=repository_url))

            result = await probe_repository(repository_url)

            if not result:
                raise errors.MissingResourceError(
                    message=f"The repository at {repository_url} does not seem to be publicly accessible."
                )
            return HTTPResponse(status=200)

        return "/repositories/<repository_url>/probe", ["GET"], _get_one_repository_probe
