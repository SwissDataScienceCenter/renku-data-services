"""Notebooks service API."""

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import cast
from urllib.parse import urlparse

from sanic import Request, empty, exceptions, json
from sanic.response import HTTPResponse, JSONResponse
from sanic_ext import validate
from ulid import ULID

from renku_data_services import base_models
from renku_data_services.base_api.auth import authenticate, authenticate_2
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_models import AnonymousAPIUser, APIUser, AuthenticatedAPIUser, Authenticator
from renku_data_services.crc.db import ResourcePoolRepository
from renku_data_services.crc.models import GpuKind
from renku_data_services.data_connectors.db import (
    DataConnectorProjectLinkRepository,
    DataConnectorRepository,
    DataConnectorSecretRepository,
)
from renku_data_services.errors import errors
from renku_data_services.notebooks import apispec, core
from renku_data_services.notebooks.api.amalthea_patches.init_containers import user_secrets_container
from renku_data_services.notebooks.api.classes.repository import Repository
from renku_data_services.notebooks.api.schemas.config_server_options import ServerOptionsEndpointResponse
from renku_data_services.notebooks.api.schemas.logs import ServerLogs
from renku_data_services.notebooks.config import NotebooksConfig
from renku_data_services.notebooks.core_sessions import (
    get_auth_secret_anonymous,
    get_auth_secret_authenticated,
    get_data_sources,
    get_extra_containers,
    get_extra_init_containers,
    patch_session,
    request_dc_secret_creation,
    request_session_secret_creation,
)
from renku_data_services.notebooks.crs import (
    AmaltheaSessionSpec,
    AmaltheaSessionV1Alpha1,
    Authentication,
    AuthenticationType,
    Culling,
    ExtraVolume,
    ExtraVolumeMount,
    Ingress,
    InitContainer,
    Metadata,
    ReconcileStrategy,
    Resources,
    Session,
    SessionEnvItem,
    Storage,
    TlsSecret,
)
from renku_data_services.notebooks.errors.intermittent import AnonymousUserPatchError
from renku_data_services.notebooks.models import ExtraSecret
from renku_data_services.notebooks.util.kubernetes_ import (
    renku_2_make_server_name,
)
from renku_data_services.notebooks.utils import (
    node_affinity_from_resource_class,
    tolerations_from_resource_class,
)
from renku_data_services.project.db import ProjectRepository, ProjectSessionSecretRepository
from renku_data_services.repositories.db import GitRepositoriesRepository
from renku_data_services.session.db import SessionRepository
from renku_data_services.storage.db import StorageRepository
from renku_data_services.users.db import UserRepo


@dataclass(kw_only=True)
class NotebooksBP(CustomBlueprint):
    """Handlers for manipulating notebooks."""

    authenticator: Authenticator
    nb_config: NotebooksConfig
    git_repo: GitRepositoriesRepository
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
                raise exceptions.NotFound(message=err.message)
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
                raise exceptions.NotFound(message=err.message)
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
    data_connector_project_link_repo: DataConnectorProjectLinkRepository
    data_connector_secret_repo: DataConnectorSecretRepository

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
            # gitlab_client = NotebooksGitlabClient(self.nb_config.git.url, internal_gitlab_user.access_token)
            launcher = await self.session_repo.get_launcher(user, ULID.from_str(body.launcher_id))
            project = await self.project_repo.get_project(user=user, project_id=launcher.project_id)
            server_name = renku_2_make_server_name(
                user=user, project_id=str(launcher.project_id), launcher_id=body.launcher_id
            )
            existing_session = await self.nb_config.k8s_v2_client.get_server(server_name, user.id)
            if existing_session is not None and existing_session.spec is not None:
                return json(existing_session.as_apispec().model_dump(exclude_none=True, mode="json"))
            environment = launcher.environment
            image = environment.container_image
            image_workdir = await core.docker_image_workdir(
                self.nb_config, environment.container_image, internal_gitlab_user
            )
            default_resource_class = await self.rp_repo.get_default_resource_class()
            if default_resource_class.id is None:
                raise errors.ProgrammingError(message="The default resource class has to have an ID", quiet=True)
            resource_class_id: int
            if body.resource_class_id is None:
                resource_class = await self.rp_repo.get_default_resource_class()
                # TODO: Add types for saved and unsaved resource class
                resource_class_id = cast(int, resource_class.id)
            else:
                resource_class = await self.rp_repo.get_resource_class(user, body.resource_class_id)
                # TODO: Add types for saved and unsaved resource class
                resource_class_id = body.resource_class_id
            await self.nb_config.crc_validator.validate_class_storage(user, resource_class_id, body.disk_storage)
            work_dir_fallback = PurePosixPath("/home/jovyan")
            work_dir = environment.working_directory or image_workdir or work_dir_fallback
            storage_mount_fallback = work_dir / "work"
            storage_mount = launcher.environment.mount_directory or storage_mount_fallback
            secrets_mount_directory = storage_mount / project.secrets_mount_directory
            session_secrets = await self.project_session_secret_repo.get_all_session_secrets_from_project(
                user=user, project_id=project.id
            )
            data_connectors_stream = self.data_connector_secret_repo.get_data_connectors_with_secrets(user, project.id)
            git_providers = await self.nb_config.git_provider_helper.get_providers(user=user)
            repositories: list[Repository] = []
            for repo in project.repositories:
                found_provider_id: str | None = None
                for provider in git_providers:
                    if urlparse(provider.url).netloc == urlparse(repo).netloc:
                        found_provider_id = provider.id
                        break
                repositories.append(Repository(url=repo, provider=found_provider_id))

            # User secrets
            extra_volume_mounts: list[ExtraVolumeMount] = []
            extra_volumes: list[ExtraVolume] = []
            extra_init_containers: list[InitContainer] = []
            user_secrets_container_patches = user_secrets_container(
                user=user,
                config=self.nb_config,
                secrets_mount_directory=secrets_mount_directory.as_posix(),
                k8s_secret_name=f"{server_name}-secrets",
                session_secrets=session_secrets,
            )
            if user_secrets_container_patches is not None:
                (init_container_session_secret, volumes_session_secret, volume_mounts_session_secret) = (
                    user_secrets_container_patches
                )
                extra_volumes.extend(volumes_session_secret)
                extra_volume_mounts.extend(volume_mounts_session_secret)
                extra_init_containers.append(init_container_session_secret)

            secrets_to_create: list[ExtraSecret] = []
            data_sources, data_secrets, enc_secrets = await get_data_sources(
                nb_config=self.nb_config,
                server_name=server_name,
                user=user,
                data_connectors_stream=data_connectors_stream,
                work_dir=work_dir,
                cloud_storage_overrides=body.cloudstorage or [],
                user_repo=self.user_repo,
            )
            secrets_to_create.extend(data_secrets)
            extra_init_containers_dc, extra_init_volumes_dc = await get_extra_init_containers(
                self.nb_config,
                user,
                repositories,
                git_providers,
                storage_mount,
                work_dir,
            )
            extra_containers = await get_extra_containers(self.nb_config, user, repositories, git_providers)
            extra_volumes.extend(extra_init_volumes_dc)
            extra_init_containers.extend(extra_init_containers_dc)

            base_server_url = self.nb_config.sessions.ingress.base_url(server_name)
            base_server_path = self.nb_config.sessions.ingress.base_path(server_name)
            ui_path: str = (
                f"{base_server_path.rstrip("/")}/{environment.default_url.lstrip("/")}"
                if len(environment.default_url) > 0
                else base_server_path
            )
            annotations: dict[str, str] = {
                "renku.io/project_id": str(launcher.project_id),
                "renku.io/launcher_id": body.launcher_id,
                "renku.io/resource_class_id": str(body.resource_class_id or default_resource_class.id),
            }
            requests: dict[str, str | int] = {
                "cpu": str(round(resource_class.cpu * 1000)) + "m",
                "memory": f"{resource_class.memory}Gi",
            }
            limits: dict[str, str | int] = {}
            if resource_class.gpu > 0:
                gpu_name = GpuKind.NVIDIA.value + "/gpu"
                requests[gpu_name] = resource_class.gpu
                limits[gpu_name] = resource_class.gpu
            if isinstance(user, AuthenticatedAPIUser):
                auth_secret = await get_auth_secret_authenticated(self.nb_config, user, server_name)
            else:
                auth_secret = await get_auth_secret_anonymous(self.nb_config, server_name, request)
            if auth_secret.volume:
                extra_volumes.append(auth_secret.volume)
            secrets_to_create.append(auth_secret)
            manifest = AmaltheaSessionV1Alpha1(
                metadata=Metadata(name=server_name, annotations=annotations),
                spec=AmaltheaSessionSpec(
                    codeRepositories=[],
                    hibernated=False,
                    reconcileStrategy=ReconcileStrategy.whenFailedOrHibernated,
                    priorityClassName=resource_class.quota,
                    session=Session(
                        image=image,
                        urlPath=ui_path,
                        port=environment.port,
                        storage=Storage(
                            className=self.nb_config.sessions.storage.pvs_storage_class,
                            size=str(body.disk_storage) + "G",
                            mountPath=storage_mount.as_posix(),
                        ),
                        workingDir=work_dir.as_posix(),
                        runAsUser=environment.uid,
                        runAsGroup=environment.gid,
                        resources=Resources(requests=requests, limits=limits if len(limits) > 0 else None),
                        extraVolumeMounts=extra_volume_mounts,
                        command=environment.command,
                        args=environment.args,
                        shmSize="1G",
                        env=[
                            SessionEnvItem(name="RENKU_BASE_URL_PATH", value=base_server_path),
                            SessionEnvItem(name="RENKU_BASE_URL", value=base_server_url),
                            SessionEnvItem(name="RENKU_MOUNT_DIR", value=storage_mount.as_posix()),
                            SessionEnvItem(name="RENKU_SESSION", value="1"),
                            SessionEnvItem(name="RENKU_SESSION_IP", value="0.0.0.0"),  # nosec B104
                            SessionEnvItem(name="RENKU_SESSION_PORT", value=f"{environment.port}"),
                            SessionEnvItem(name="RENKU_WORKING_DIR", value=work_dir.as_posix()),
                        ],
                    ),
                    ingress=Ingress(
                        host=self.nb_config.sessions.ingress.host,
                        ingressClassName=self.nb_config.sessions.ingress.annotations.get("kubernetes.io/ingress.class"),
                        annotations=self.nb_config.sessions.ingress.annotations,
                        tlsSecret=TlsSecret(adopt=False, name=self.nb_config.sessions.ingress.tls_secret)
                        if self.nb_config.sessions.ingress.tls_secret is not None
                        else None,
                        pathPrefix=base_server_path,
                    ),
                    extraContainers=extra_containers,
                    initContainers=extra_init_containers,
                    extraVolumes=extra_volumes,
                    culling=Culling(
                        maxAge=f"{self.nb_config.sessions.culling.registered.max_age_seconds}s",
                        maxFailedDuration=f"{self.nb_config.sessions.culling.registered.failed_seconds}s",
                        maxHibernatedDuration=f"{self.nb_config.sessions.culling.registered.hibernated_seconds}s",
                        maxIdleDuration=f"{self.nb_config.sessions.culling.registered.idle_seconds}s",
                        maxStartingDuration=f"{self.nb_config.sessions.culling.registered.pending_seconds}s",
                    ),
                    authentication=Authentication(
                        enabled=True,
                        type=AuthenticationType.oauth2proxy
                        if isinstance(user, AuthenticatedAPIUser)
                        else AuthenticationType.token,
                        secretRef=auth_secret.key_ref("auth"),
                        extraVolumeMounts=[auth_secret.volume_mount] if auth_secret.volume_mount else [],
                    ),
                    dataSources=data_sources,
                    tolerations=tolerations_from_resource_class(
                        resource_class, self.nb_config.sessions.tolerations_model
                    ),
                    affinity=node_affinity_from_resource_class(resource_class, self.nb_config.sessions.affinity_model),
                ),
            )
            for s in secrets_to_create:
                await self.nb_config.k8s_v2_client.create_secret(s.secret)
            try:
                manifest = await self.nb_config.k8s_v2_client.create_server(manifest, user.id)
            except Exception:
                for s in secrets_to_create:
                    await self.nb_config.k8s_v2_client.delete_secret(s.secret.metadata.name)
                raise errors.ProgrammingError(message="Could not start the amalthea session")
            else:
                try:
                    await request_session_secret_creation(user, self.nb_config, manifest, session_secrets)
                    await request_dc_secret_creation(user, self.nb_config, manifest, enc_secrets)
                except Exception:
                    await self.nb_config.k8s_v2_client.delete_server(server_name, user.id)
                    raise

            return json(manifest.as_apispec().model_dump(mode="json", exclude_none=True), 201)

        return "/sessions", ["POST"], _handler

    def get_all(self) -> BlueprintFactoryResponse:
        """Get all sessions for a user."""

        @authenticate(self.authenticator)
        async def _handler(_: Request, user: AuthenticatedAPIUser | AnonymousAPIUser) -> HTTPResponse:
            sessions = await self.nb_config.k8s_v2_client.list_servers(user.id)
            output: list[dict] = []
            for session in sessions:
                output.append(session.as_apispec().model_dump(exclude_none=True, mode="json"))
            return json(output)

        return "/sessions", ["GET"], _handler

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific session for a user."""

        @authenticate(self.authenticator)
        async def _handler(_: Request, user: AuthenticatedAPIUser | AnonymousAPIUser, session_id: str) -> HTTPResponse:
            session = await self.nb_config.k8s_v2_client.get_server(session_id, user.id)
            if session is None:
                raise errors.ValidationError(message=f"The session with ID {session_id} does not exist.", quiet=True)
            return json(session.as_apispec().model_dump(exclude_none=True, mode="json"))

        return "/sessions/<session_id>", ["GET"], _handler

    def delete(self) -> BlueprintFactoryResponse:
        """Fully delete a session with the new operator."""

        @authenticate(self.authenticator)
        async def _handler(_: Request, user: AuthenticatedAPIUser | AnonymousAPIUser, session_id: str) -> HTTPResponse:
            await self.nb_config.k8s_v2_client.delete_server(session_id, user.id)
            return empty()

        return "/sessions/<session_id>", ["DELETE"], _handler

    def patch(self) -> BlueprintFactoryResponse:
        """Patch a session."""

        @authenticate(self.authenticator)
        @validate(json=apispec.SessionPatchRequest)
        async def _handler(
            _: Request,
            user: AuthenticatedAPIUser | AnonymousAPIUser,
            session_id: str,
            body: apispec.SessionPatchRequest,
        ) -> HTTPResponse:
            new_session = await patch_session(body, session_id, self.nb_config, user, self.rp_repo, self.project_repo)
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
            logs = await self.nb_config.k8s_v2_client.get_server_logs(session_id, user.id, query.max_lines)
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
        ) -> HTTPResponse:
            image_url = request.get_args().get("image_url")
            if not isinstance(image_url, str):
                raise ValueError("required string of image url")

            status = 200 if await core.docker_image_exists(self.nb_config, image_url, internal_gitlab_user) else 404
            return HTTPResponse(status=status)

        return "/sessions/images", ["GET"], _check_docker_image
