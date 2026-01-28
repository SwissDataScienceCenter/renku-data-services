"""Notebooks service API."""

from dataclasses import dataclass

from sanic import Request, empty, json
from sanic.response import HTTPResponse, JSONResponse
from sanic_ext import validate

from renku_data_services import base_models
from renku_data_services.app_config import logging
from renku_data_services.base_api.auth import authenticate, authenticate_2
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_models import AnonymousAPIUser, APIUser, AuthenticatedAPIUser
from renku_data_services.base_models.metrics import MetricsService
from renku_data_services.connected_services.models import ConnectionStatus
from renku_data_services.connected_services.oauth_http import OAuthHttpClientFactory
from renku_data_services.crc.db import ClusterRepository, ResourcePoolRepository
from renku_data_services.data_connectors.db import (
    DataConnectorRepository,
    DataConnectorSecretRepository,
)
from renku_data_services.errors import errors
from renku_data_services.notebooks import apispec
from renku_data_services.notebooks.api.classes.image import Image
from renku_data_services.notebooks.config import GitProviderHelperProto, NotebooksConfig
from renku_data_services.notebooks.core_sessions import (
    patch_session,
    start_session,
    validate_session_post_request,
)
from renku_data_services.notebooks.data_sources import DataSourceRepository
from renku_data_services.notebooks.image_check import ImageCheckRepository
from renku_data_services.project.db import ProjectRepository, ProjectSessionSecretRepository
from renku_data_services.session.db import SessionRepository
from renku_data_services.storage.db import StorageRepository
from renku_data_services.users.db import UserRepo

logger = logging.getLogger(__name__)


@dataclass(kw_only=True)
class NotebooksNewBP(CustomBlueprint):
    """Handlers for manipulating notebooks for the new Amalthea operator."""

    authenticator: base_models.Authenticator
    internal_gitlab_authenticator: base_models.Authenticator
    nb_config: NotebooksConfig
    cluster_repo: ClusterRepository
    data_connector_repo: DataConnectorRepository
    data_connector_secret_repo: DataConnectorSecretRepository
    git_provider_helper: GitProviderHelperProto
    oauth_client_factory: OAuthHttpClientFactory
    data_source_repo: DataSourceRepository
    image_check_repo: ImageCheckRepository
    project_repo: ProjectRepository
    project_session_secret_repo: ProjectSessionSecretRepository
    rp_repo: ResourcePoolRepository
    session_repo: SessionRepository
    storage_repo: StorageRepository
    user_repo: UserRepo
    metrics: MetricsService

    def start(self) -> BlueprintFactoryResponse:
        """Start a session with the new operator."""

        @authenticate_2(self.authenticator, self.internal_gitlab_authenticator)
        @validate(json=apispec.SessionPostRequest)
        async def _handler(
            request: Request,
            user: AuthenticatedAPIUser | AnonymousAPIUser,
            internal_gitlab_user: APIUser,
            body: apispec.SessionPostRequest,
        ) -> JSONResponse:
            launch_request = validate_session_post_request(body=body)
            session, created = await start_session(
                request=request,
                launch_request=launch_request,
                user=user,
                internal_gitlab_user=internal_gitlab_user,
                nb_config=self.nb_config,
                git_provider_helper=self.git_provider_helper,
                cluster_repo=self.cluster_repo,
                data_connector_secret_repo=self.data_connector_secret_repo,
                project_repo=self.project_repo,
                project_session_secret_repo=self.project_session_secret_repo,
                rp_repo=self.rp_repo,
                session_repo=self.session_repo,
                user_repo=self.user_repo,
                metrics=self.metrics,
                image_check_repo=self.image_check_repo,
                data_source_repo=self.data_source_repo,
            )
            status = 201 if created else 200
            return json(session.as_apispec().model_dump(exclude_none=True, mode="json"), status)

        return "/sessions", ["POST"], _handler

    def get_all(self) -> BlueprintFactoryResponse:
        """Get all sessions for a user."""

        @authenticate(self.authenticator)
        async def _handler(_: Request, user: AuthenticatedAPIUser | AnonymousAPIUser) -> HTTPResponse:
            sessions = await self.nb_config.k8s_v2_client.list_sessions(user.id)
            output: list[dict] = []
            for session in sessions:
                output.append(session.as_apispec().model_dump(exclude_none=True, mode="json"))
            return json(output)

        return "/sessions", ["GET"], _handler

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific session for a user."""

        @authenticate(self.authenticator)
        async def _handler(_: Request, user: AuthenticatedAPIUser | AnonymousAPIUser, session_id: str) -> HTTPResponse:
            session = await self.nb_config.k8s_v2_client.get_session(session_id, user.id)
            if session is None:
                raise errors.ValidationError(message=f"The session with ID {session_id} does not exist.", quiet=True)
            return json(session.as_apispec().model_dump(exclude_none=True, mode="json"))

        return "/sessions/<session_id>", ["GET"], _handler

    def delete(self) -> BlueprintFactoryResponse:
        """Fully delete a session with the new operator."""

        @authenticate(self.authenticator)
        async def _handler(_: Request, user: AuthenticatedAPIUser | AnonymousAPIUser, session_id: str) -> HTTPResponse:
            await self.nb_config.k8s_v2_client.delete_session(session_id, user.id)
            await self.metrics.session_stopped(user, metadata={"session_id": session_id})
            return empty()

        return "/sessions/<session_id>", ["DELETE"], _handler

    def patch(self) -> BlueprintFactoryResponse:
        """Patch a session."""

        @authenticate_2(self.authenticator, self.internal_gitlab_authenticator)
        @validate(json=apispec.SessionPatchRequest)
        async def _handler(
            request: Request,
            user: AuthenticatedAPIUser | AnonymousAPIUser,
            internal_gitlab_user: APIUser,
            session_id: str,
            body: apispec.SessionPatchRequest,
        ) -> HTTPResponse:
            new_session = await patch_session(
                request=request,
                body=body,
                session_id=session_id,
                user=user,
                internal_gitlab_user=internal_gitlab_user,
                nb_config=self.nb_config,
                git_provider_helper=self.git_provider_helper,
                data_connector_secret_repo=self.data_connector_secret_repo,
                project_repo=self.project_repo,
                project_session_secret_repo=self.project_session_secret_repo,
                rp_repo=self.rp_repo,
                session_repo=self.session_repo,
                metrics=self.metrics,
                image_check_repo=self.image_check_repo,
                data_source_repo=self.data_source_repo,
            )
            return json(new_session.as_apispec().model_dump(exclude_none=True, mode="json"))

        return "/sessions/<session_id>", ["PATCH"], _handler

    def logs(self) -> BlueprintFactoryResponse:
        """Get logs from the session."""

        @authenticate(self.authenticator)
        @validate(query=apispec.SessionsSessionIdLogsGetParametersQuery)
        async def _handler(
            _: Request,
            user: AuthenticatedAPIUser | AnonymousAPIUser,
            session_id: str,
            query: apispec.SessionsSessionIdLogsGetParametersQuery,
        ) -> HTTPResponse:
            logs = await self.nb_config.k8s_v2_client.get_session_logs(session_id, user.id, query.max_lines)
            return json(apispec.SessionLogsResponse.model_validate(logs).model_dump(exclude_none=True))

        return "/sessions/<session_id>/logs", ["GET"], _handler

    def check_docker_image(self) -> BlueprintFactoryResponse:
        """Return the availability of the docker image."""

        @authenticate_2(self.authenticator, self.internal_gitlab_authenticator)
        @validate(query=apispec.SessionsImagesGetParametersQuery)
        async def _check_docker_image(
            request: Request,
            user: AnonymousAPIUser | AuthenticatedAPIUser,
            internal_gitlab_user: APIUser,
            query: apispec.SessionsImagesGetParametersQuery,
        ) -> JSONResponse:
            image = Image.from_path(query.image_url)
            result = await self.image_check_repo.check_image(
                user=user,
                gitlab_user=internal_gitlab_user,
                image=image,
            )
            logger.info(f"Checked image {query.image_url}: {result}")
            conn = None
            if result.connection:
                match result.connection.status:
                    case ConnectionStatus.connected:
                        if result.error is not None:
                            status = apispec.ImageConnectionStatus.invalid_credentials
                        else:
                            status = apispec.ImageConnectionStatus.connected

                    case ConnectionStatus.pending:
                        status = apispec.ImageConnectionStatus.pending

                conn = apispec.ImageConnection(
                    id=str(result.connection.id), provider_id=result.connection.provider_id, status=status
                )

            provider: apispec.ImageProvider | None = None
            if result.client:
                provider = apispec.ImageProvider(
                    id=result.client.id, name=result.client.display_name, url=result.client.url
                )

            platforms = None
            if result.platforms:
                platforms = [apispec.ImagePlatform.model_validate(p) for p in result.platforms]

            resp = apispec.ImageCheckResponse(
                accessible=result.accessible, platforms=platforms, connection=conn, provider=provider
            )

            return json(resp.model_dump(exclude_none=True, mode="json"))

        return "/sessions/images", ["GET"], _check_docker_image
