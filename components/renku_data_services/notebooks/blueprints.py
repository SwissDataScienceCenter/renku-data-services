"""Notebooks service API."""

from dataclasses import dataclass

from sanic import Request, empty, exceptions, json
from sanic.response import HTTPResponse, JSONResponse
from sanic_ext import validate

from renku_data_services import base_models
from renku_data_services.app_config import logging
from renku_data_services.base_api.auth import authenticate, authenticate_2
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_models import AnonymousAPIUser, APIUser, AuthenticatedAPIUser, Authenticator
from renku_data_services.base_models.metrics import MetricsService
from renku_data_services.connected_services.db import ConnectedServicesRepository
from renku_data_services.connected_services.models import ConnectionStatus
from renku_data_services.crc.db import ClusterRepository, ResourcePoolRepository
from renku_data_services.data_connectors.db import (
    DataConnectorRepository,
    DataConnectorSecretRepository,
)
from renku_data_services.errors import errors
from renku_data_services.notebooks import apispec, core, image_check
from renku_data_services.notebooks.api.classes.image import Image
from renku_data_services.notebooks.api.schemas.config_server_options import ServerOptionsEndpointResponse
from renku_data_services.notebooks.api.schemas.logs import ServerLogs
from renku_data_services.notebooks.config import NotebooksConfig
from renku_data_services.notebooks.core_sessions import (
    patch_session,
    start_session,
)
from renku_data_services.notebooks.errors.intermittent import AnonymousUserPatchError
from renku_data_services.project.db import ProjectRepository, ProjectSessionSecretRepository
from renku_data_services.session.db import SessionRepository
from renku_data_services.storage.db import StorageRepository
from renku_data_services.users.db import UserRepo

logger = logging.getLogger(__name__)


@dataclass(kw_only=True)
class NotebooksBP(CustomBlueprint):
    """Handlers for manipulating notebooks."""

    authenticator: Authenticator
    nb_config: NotebooksConfig
    internal_gitlab_authenticator: base_models.Authenticator
    rp_repo: ResourcePoolRepository
    user_repo: UserRepo
    storage_repo: StorageRepository

    def version(self) -> BlueprintFactoryResponse:
        """Return notebook services version."""

        async def _version(_: Request) -> JSONResponse:
            return json(core.notebooks_info(self.nb_config))

        return "/notebooks/version", ["GET"], _version

    def user_servers(self) -> BlueprintFactoryResponse:
        """Return a JSON of running servers for the user."""

        @authenticate(self.authenticator)
        async def _user_servers(
            request: Request, user: AnonymousAPIUser | AuthenticatedAPIUser, **query_params: dict
        ) -> JSONResponse:
            filter_attrs = list(filter(lambda x: x[1] is not None, request.get_query_args()))
            filtered_servers = await core.user_servers(self.nb_config, user, filter_attrs)
            return core.serialize_v1_servers(filtered_servers, self.nb_config)

        return "/notebooks/servers", ["GET"], _user_servers

    def user_server(self) -> BlueprintFactoryResponse:
        """Returns a user server based on its ID."""

        @authenticate(self.authenticator)
        async def _user_server(
            request: Request, user: AnonymousAPIUser | AuthenticatedAPIUser, server_name: str
        ) -> JSONResponse:
            server = await core.user_server(self.nb_config, user, server_name)
            return core.serialize_v1_server(server, self.nb_config)

        return "/notebooks/servers/<server_name>", ["GET"], _user_server

    def launch_notebook(self) -> BlueprintFactoryResponse:
        """Start a renku session."""

        @authenticate_2(self.authenticator, self.internal_gitlab_authenticator)
        @validate(json=apispec.LaunchNotebookRequestOld)
        async def _launch_notebook(
            request: Request,
            user: AnonymousAPIUser | AuthenticatedAPIUser,
            internal_gitlab_user: APIUser,
            body: apispec.LaunchNotebookRequestOld,
        ) -> JSONResponse:
            server, status_code = await core.launch_notebook(
                self.nb_config,
                user,
                internal_gitlab_user,
                body,
                user_repo=self.user_repo,
                storage_repo=self.storage_repo,
            )
            return core.serialize_v1_server(server, self.nb_config, status_code)

        return "/notebooks/servers", ["POST"], _launch_notebook

    def patch_server(self) -> BlueprintFactoryResponse:
        """Patch a user server by name based on the query param."""

        @authenticate_2(self.authenticator, self.internal_gitlab_authenticator)
        @validate(json=apispec.PatchServerRequest)
        async def _patch_server(
            request: Request,
            user: AnonymousAPIUser | AuthenticatedAPIUser,
            internal_gitlab_user: APIUser,
            server_name: str,
            body: apispec.PatchServerRequest,
        ) -> JSONResponse:
            if isinstance(user, AnonymousAPIUser):
                raise AnonymousUserPatchError()

            manifest = await core.patch_server(self.nb_config, user, internal_gitlab_user, server_name, body)
            return core.serialize_v1_server(manifest, self.nb_config)

        return "/notebooks/servers/<server_name>", ["PATCH"], _patch_server

    def stop_server(self) -> BlueprintFactoryResponse:
        """Stop user server by name."""

        @authenticate(self.authenticator)
        async def _stop_server(
            _: Request, user: AnonymousAPIUser | AuthenticatedAPIUser, server_name: str
        ) -> HTTPResponse:
            try:
                await core.stop_server(self.nb_config, user, server_name)
            except errors.MissingResourceError as err:
                raise exceptions.NotFound(message=err.message) from err
            return HTTPResponse(status=204)

        return "/notebooks/servers/<server_name>", ["DELETE"], _stop_server

    def server_options(self) -> BlueprintFactoryResponse:
        """Return a set of configurable server options."""

        async def _server_options(request: Request) -> JSONResponse:
            return json(ServerOptionsEndpointResponse().dump(core.server_options(self.nb_config)))

        return "/notebooks/server_options", ["GET"], _server_options

    def server_logs(self) -> BlueprintFactoryResponse:
        """Return the logs of the running server."""

        @authenticate(self.authenticator)
        async def _server_logs(
            request: Request, user: AnonymousAPIUser | AuthenticatedAPIUser, server_name: str
        ) -> JSONResponse:
            args: dict[str, str | int] = request.get_args()
            max_lines = int(args.get("max_lines", 250))
            try:
                logs = await core.server_logs(self.nb_config, user, server_name, max_lines)
            except errors.MissingResourceError as err:
                raise exceptions.NotFound(message=err.message) from err
            return json(ServerLogs().dump(logs))

        return "/notebooks/logs/<server_name>", ["GET"], _server_logs

    def check_docker_image(self) -> BlueprintFactoryResponse:
        """Return the availability of the docker image."""

        @authenticate_2(self.authenticator, self.internal_gitlab_authenticator)
        @validate(query=apispec.NotebooksImagesGetParametersQuery)
        async def _check_docker_image(
            request: Request,
            user: AnonymousAPIUser | AuthenticatedAPIUser,
            internal_gitlab_user: APIUser,
            query: apispec.NotebooksImagesGetParametersQuery,
        ) -> HTTPResponse:
            image_url = request.get_args().get("image_url")
            if not isinstance(image_url, str):
                raise ValueError("required string of image url")

            status = 200 if await core.docker_image_exists(self.nb_config, image_url, internal_gitlab_user) else 404
            return HTTPResponse(status=status)

        return "/notebooks/images", ["GET"], _check_docker_image


@dataclass(kw_only=True)
class NotebooksNewBP(CustomBlueprint):
    """Handlers for manipulating notebooks for the new Amalthea operator."""

    authenticator: base_models.Authenticator
    internal_gitlab_authenticator: base_models.Authenticator
    nb_config: NotebooksConfig
    project_repo: ProjectRepository
    project_session_secret_repo: ProjectSessionSecretRepository
    session_repo: SessionRepository
    rp_repo: ResourcePoolRepository
    storage_repo: StorageRepository
    user_repo: UserRepo
    data_connector_repo: DataConnectorRepository
    data_connector_secret_repo: DataConnectorSecretRepository
    metrics: MetricsService
    cluster_repo: ClusterRepository
    connected_svcs_repo: ConnectedServicesRepository

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
            session, created = await start_session(
                request=request,
                body=body,
                user=user,
                internal_gitlab_user=internal_gitlab_user,
                nb_config=self.nb_config,
                cluster_repo=self.cluster_repo,
                data_connector_secret_repo=self.data_connector_secret_repo,
                project_repo=self.project_repo,
                project_session_secret_repo=self.project_session_secret_repo,
                rp_repo=self.rp_repo,
                session_repo=self.session_repo,
                user_repo=self.user_repo,
                metrics=self.metrics,
                connected_svcs_repo=self.connected_svcs_repo,
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
            _: Request,
            user: AuthenticatedAPIUser | AnonymousAPIUser,
            internal_gitlab_user: APIUser,
            session_id: str,
            body: apispec.SessionPatchRequest,
        ) -> HTTPResponse:
            new_session = await patch_session(
                body=body,
                session_id=session_id,
                user=user,
                internal_gitlab_user=internal_gitlab_user,
                nb_config=self.nb_config,
                project_repo=self.project_repo,
                project_session_secret_repo=self.project_session_secret_repo,
                rp_repo=self.rp_repo,
                session_repo=self.session_repo,
                metrics=self.metrics,
                connected_svcs_repo=self.connected_svcs_repo,
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
            result = await image_check.check_image(
                image,
                user,
                self.connected_svcs_repo,
                image_check.InternalGitLabConfig(internal_gitlab_user, self.nb_config),
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

            resp = apispec.ImageCheckResponse(accessible=result.accessible, connection=conn, provider=provider)

            return json(resp.model_dump(exclude_none=True, mode="json"))

        return "/sessions/images", ["GET"], _check_docker_image
