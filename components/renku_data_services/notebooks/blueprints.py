"""Notebooks service API."""

from dataclasses import dataclass
from pathlib import PurePosixPath

from sanic import Request, empty, exceptions, json
from sanic.response import HTTPResponse, JSONResponse
from sanic_ext import validate
from ulid import ULID

from renku_data_services import base_models
from renku_data_services.base_api.auth import authenticate, authenticate_2
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_models import AnonymousAPIUser, APIUser, AuthenticatedAPIUser, Authenticator
from renku_data_services.base_models.metrics import MetricsService
from renku_data_services.crc.db import ClusterRepository, ResourcePoolRepository
from renku_data_services.data_connectors.db import (
    DataConnectorRepository,
    DataConnectorSecretRepository,
)
from renku_data_services.errors import errors
from renku_data_services.notebooks import apispec, core
from renku_data_services.notebooks.api.amalthea_patches.init_containers import user_secrets_container
from renku_data_services.notebooks.api.schemas.config_server_options import ServerOptionsEndpointResponse
from renku_data_services.notebooks.api.schemas.logs import ServerLogs
from renku_data_services.notebooks.config import NotebooksConfig
from renku_data_services.notebooks.core_sessions import (
    get_auth_secret_anonymous,
    get_auth_secret_authenticated,
    get_culling,
    get_data_sources,
    get_extra_containers,
    get_extra_init_containers,
    get_gitlab_image_pull_secret,
    get_launcher_env_variables,
    patch_session,
    repositories_from_project,
    request_dc_secret_creation,
    request_session_secret_creation,
    requires_image_pull_secret,
    resources_from_resource_class,
    verify_launcher_env_variable_overrides,
)
from renku_data_services.notebooks.crs import (
    AmaltheaSessionSpec,
    AmaltheaSessionV1Alpha1,
    Authentication,
    AuthenticationType,
    ExtraVolume,
    ExtraVolumeMount,
    ImagePullPolicy,
    ImagePullSecret,
    Ingress,
    InitContainer,
    Metadata,
    ReconcileStrategy,
    Session,
    SessionEnvItem,
    ShmSizeStr,
    SizeStr,
    Storage,
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
            launcher = await self.session_repo.get_launcher(user, ULID.from_str(body.launcher_id))
            project = await self.project_repo.get_project(user=user, project_id=launcher.project_id)
            # We have to use body.resource_class_id and not launcher.resource_class_id as it may have been overridden by
            # the user when selecting a different resource class from a different resource pool.
            cluster = await self.nb_config.k8s_v2_client.cluster_by_class_id(body.resource_class_id, user)
            server_name = renku_2_make_server_name(
                user=user, project_id=str(launcher.project_id), launcher_id=body.launcher_id, cluster_id=cluster.id
            )
            existing_session = await self.nb_config.k8s_v2_client.get_session(server_name, user.id)
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
            if body.resource_class_id is None:
                resource_pool = await self.rp_repo.get_default_resource_pool()
                resource_class = resource_pool.get_default_resource_class()
                if not resource_class and len(resource_pool.classes) > 0:
                    resource_class = resource_pool.classes[0]
                if not resource_class or not resource_class.id:
                    raise errors.ProgrammingError(message="There cannot find any resource classes in the default pool.")
            else:
                resource_pool = await self.rp_repo.get_resource_pool_from_class(user, body.resource_class_id)
                resource_class = resource_pool.get_resource_class(body.resource_class_id)
                if not resource_class or not resource_class.id:
                    raise errors.MissingResourceError(
                        message=f"The resource class with ID {body.resource_class_id} does not exist."
                    )
            await self.nb_config.crc_validator.validate_class_storage(user, resource_class.id, body.disk_storage)
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
            repositories = repositories_from_project(project, git_providers)

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
                uid=environment.uid,
                gid=environment.gid,
            )
            extra_containers = await get_extra_containers(self.nb_config, user, repositories, git_providers)
            extra_volumes.extend(extra_init_volumes_dc)
            extra_init_containers.extend(extra_init_containers_dc)

            (
                base_server_path,
                base_server_url,
                base_server_https_url,
                host,
                tls_secret,
                ingress_annotations,
            ) = await cluster.get_ingress_parameters(
                user, self.cluster_repo, self.nb_config.sessions.ingress, server_name
            )

            ui_path = f"{base_server_path}/{environment.default_url.lstrip('/')}"

            ingress = Ingress(
                host=host,
                ingressClassName=ingress_annotations.get("kubernetes.io/ingress.class"),
                annotations=ingress_annotations,
                tlsSecret=tls_secret,
                pathPrefix=base_server_path,
            )

            annotations: dict[str, str] = {
                "renku.io/project_id": str(launcher.project_id),
                "renku.io/launcher_id": body.launcher_id,
                "renku.io/resource_class_id": str(body.resource_class_id or default_resource_class.id),
            }
            if isinstance(user, AuthenticatedAPIUser):
                auth_secret = await get_auth_secret_authenticated(
                    self.nb_config, user, server_name, base_server_url, base_server_https_url, base_server_path
                )
            else:
                auth_secret = await get_auth_secret_anonymous(self.nb_config, server_name, request)
            if auth_secret.volume:
                extra_volumes.append(auth_secret.volume)

            image_pull_secret_name = None
            if isinstance(user, AuthenticatedAPIUser) and internal_gitlab_user.access_token is not None:
                needs_pull_secret = await requires_image_pull_secret(self.nb_config, image, internal_gitlab_user)

                if needs_pull_secret:
                    image_pull_secret_name = f"{server_name}-image-secret"

                    image_secret = get_gitlab_image_pull_secret(
                        self.nb_config, user, image_pull_secret_name, internal_gitlab_user.access_token
                    )
                    secrets_to_create.append(image_secret)

            secrets_to_create.append(auth_secret)

            # Raise an error if there are invalid environment variables in the request body
            verify_launcher_env_variable_overrides(launcher, body)
            env = [
                SessionEnvItem(name="RENKU_BASE_URL_PATH", value=base_server_path),
                SessionEnvItem(name="RENKU_BASE_URL", value=base_server_url),
                SessionEnvItem(name="RENKU_MOUNT_DIR", value=storage_mount.as_posix()),
                SessionEnvItem(name="RENKU_SESSION", value="1"),
                SessionEnvItem(name="RENKU_SESSION_IP", value="0.0.0.0"),  # nosec B104
                SessionEnvItem(name="RENKU_SESSION_PORT", value=f"{environment.port}"),
                SessionEnvItem(name="RENKU_WORKING_DIR", value=work_dir.as_posix()),
            ]
            launcher_env_variables = get_launcher_env_variables(launcher, body)
            if launcher_env_variables:
                env.extend(launcher_env_variables)

            storage_class = await cluster.get_storage_class(
                user, self.cluster_repo, self.nb_config.sessions.storage.pvs_storage_class
            )
            service_account_name: str | None = None
            if resource_pool.cluster:
                service_account_name = resource_pool.cluster.service_account_name
            manifest = AmaltheaSessionV1Alpha1(
                metadata=Metadata(name=server_name, annotations=annotations),
                spec=AmaltheaSessionSpec(
                    imagePullSecrets=[ImagePullSecret(name=image_pull_secret_name, adopt=True)]
                    if image_pull_secret_name
                    else [],
                    codeRepositories=[],
                    hibernated=False,
                    reconcileStrategy=ReconcileStrategy.whenFailedOrHibernated,
                    priorityClassName=resource_class.quota,
                    session=Session(
                        image=image,
                        imagePullPolicy=ImagePullPolicy.Always,
                        urlPath=ui_path,
                        port=environment.port,
                        storage=Storage(
                            className=storage_class,
                            size=SizeStr(str(body.disk_storage) + "G"),
                            mountPath=storage_mount.as_posix(),
                        ),
                        workingDir=work_dir.as_posix(),
                        runAsUser=environment.uid,
                        runAsGroup=environment.gid,
                        resources=resources_from_resource_class(resource_class),
                        extraVolumeMounts=extra_volume_mounts,
                        command=environment.command,
                        args=environment.args,
                        shmSize=ShmSizeStr("1G"),
                        env=env,
                    ),
                    ingress=ingress,
                    extraContainers=extra_containers,
                    initContainers=extra_init_containers,
                    extraVolumes=extra_volumes,
                    culling=get_culling(user, resource_pool, self.nb_config),
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
                    serviceAccountName=service_account_name,
                ),
            )
            for s in secrets_to_create:
                await self.nb_config.k8s_v2_client.create_secret(s.secret, cluster)
            try:
                manifest = await self.nb_config.k8s_v2_client.create_session(manifest, user)
            except Exception as err:
                for s in secrets_to_create:
                    await self.nb_config.k8s_v2_client.delete_secret(s.secret.metadata.name, cluster)
                raise errors.ProgrammingError(message="Could not start the amalthea session") from err
            else:
                try:
                    await request_session_secret_creation(user, self.nb_config, manifest, session_secrets)
                    await request_dc_secret_creation(user, self.nb_config, manifest, enc_secrets)
                except Exception:
                    await self.nb_config.k8s_v2_client.delete_session(server_name, user.id)
                    raise

            await self.metrics.user_requested_session_launch(
                user=user,
                metadata={
                    "cpu": int(resource_class.cpu * 1000),
                    "memory": resource_class.memory,
                    "gpu": resource_class.gpu,
                    "storage": body.disk_storage,
                    "resource_class_id": resource_class.id,
                    "resource_pool_id": resource_pool.id or "",
                    "resource_class_name": f"{resource_pool.name}.{resource_class.name}",
                    "session_id": server_name,
                },
            )
            return json(manifest.as_apispec().model_dump(mode="json", exclude_none=True), 201)

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
                body,
                session_id,
                self.nb_config,
                user,
                internal_gitlab_user,
                rp_repo=self.rp_repo,
                project_repo=self.project_repo,
                metrics=self.metrics,
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
        ) -> HTTPResponse:
            image_url = request.get_args().get("image_url")
            if not isinstance(image_url, str):
                raise ValueError("required string of image url")

            status = 200 if await core.docker_image_exists(self.nb_config, image_url, internal_gitlab_user) else 404
            return HTTPResponse(status=status)

        return "/sessions/images", ["GET"], _check_docker_image
