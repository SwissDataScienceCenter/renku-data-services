"""Notebooks service API."""

import base64
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from math import floor
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urljoin, urlparse

from kubernetes.client import V1ObjectMeta, V1Secret
from sanic import Request, empty, exceptions, json
from sanic.log import logger
from sanic.response import HTTPResponse, JSONResponse
from sanic_ext import validate
from toml import dumps
from ulid import ULID
from yaml import safe_dump

from renku_data_services import base_models
from renku_data_services.base_api.auth import authenticate, authenticate_2
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_models import AnonymousAPIUser, APIUser, AuthenticatedAPIUser, Authenticator
from renku_data_services.crc.db import ResourcePoolRepository
from renku_data_services.errors import errors
from renku_data_services.notebooks import apispec, core
from renku_data_services.notebooks.api.amalthea_patches import git_proxy, init_containers
from renku_data_services.notebooks.api.classes.repository import Repository
from renku_data_services.notebooks.api.classes.server import Renku2UserServer
from renku_data_services.notebooks.api.schemas.cloud_storage import RCloneStorage
from renku_data_services.notebooks.api.schemas.config_server_options import ServerOptionsEndpointResponse
from renku_data_services.notebooks.api.schemas.logs import ServerLogs
from renku_data_services.notebooks.api.schemas.secrets import K8sUserSecrets
from renku_data_services.notebooks.api.schemas.servers_get import (
    NotebookResponse,
    ServersGetResponse,
)
from renku_data_services.notebooks.config import NotebooksConfig

from renku_data_services.notebooks.crs import (
    AmaltheaSessionSpec,
    AmaltheaSessionV1Alpha1,
    Authentication,
    AuthenticationType,
    Culling,
    DataSource,
    ExtraContainer,
    ExtraVolume,
    ExtraVolumeMount,
    Ingress,
    InitContainer,
    Metadata,
    Resources,
    SecretAsVolume,
    SecretAsVolumeItem,
    SecretRefKey,
    SecretRefWhole,
    Session,
    SessionEnvItem,
    State,
    Storage,
    TlsSecret,
)
from renku_data_services.notebooks.errors.intermittent import AnonymousUserPatchError

from renku_data_services.notebooks.util.kubernetes_ import (
    renku_2_make_server_name,
)
from renku_data_services.project.db import ProjectRepository
from renku_data_services.repositories.db import GitRepositoriesRepository
from renku_data_services.session.db import SessionRepository
from renku_data_services.storage.db import StorageV2Repository


@dataclass(kw_only=True)
class NotebooksBP(CustomBlueprint):
    """Handlers for manipulating notebooks."""

    authenticator: Authenticator
    nb_config: NotebooksConfig
    git_repo: GitRepositoriesRepository
    internal_gitlab_authenticator: base_models.Authenticator
    rp_repo: ResourcePoolRepository

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
            return json(ServersGetResponse().dump({"servers": filtered_servers}))

        return "/notebooks/servers", ["GET"], _user_servers

    def user_server(self) -> BlueprintFactoryResponse:
        """Returns a user server based on its ID."""

        @authenticate(self.authenticator)
        async def _user_server(
            request: Request, user: AnonymousAPIUser | AuthenticatedAPIUser, server_name: str
        ) -> JSONResponse:

            server = await core.user_server(self.nb_config, user, server_name)
            return json(NotebookResponse().dump(server))

        return "/notebooks/servers/<server_name>", ["GET"], _user_server

    def launch_notebook(self) -> BlueprintFactoryResponse:
        """Start a renku session."""

        @authenticate_2(self.authenticator, self.internal_gitlab_authenticator)
        @validate(json=apispec.LaunchNotebookRequest)
        async def _launch_notebook(
            request: Request,
            user: AnonymousAPIUser | AuthenticatedAPIUser,
            internal_gitlab_user: APIUser,
            body: apispec.LaunchNotebookRequest,
        ) -> JSONResponse:
            server, status_code = await core.launch_notebook(self.nb_config, user, internal_gitlab_user, body)
            return json(NotebookResponse().dump(server), status_code)

        return "/notebooks/servers", ["POST"], _launch_notebook

    def launch_notebook_old(self) -> BlueprintFactoryResponse:
        """Start a renku session using the old operator."""

        @authenticate_2(self.authenticator, self.internal_gitlab_authenticator)
        @validate(json=apispec.LaunchNotebookRequestOld)
        async def _launch_notebook_old(
            request: Request,
            user: AnonymousAPIUser | AuthenticatedAPIUser,
            internal_gitlab_user: APIUser,
            body: apispec.LaunchNotebookRequestOld,
        ) -> JSONResponse:
            server, status_code = await core.launch_notebook_old(
                self.nb_config,
                user,
                internal_gitlab_user,
                body,
            )
            return json(NotebookResponse().dump(server), status_code)

        return "/notebooks/old/servers", ["POST"], _launch_notebook_old

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
            notebook_response = apispec.NotebookResponse.parse_obj(manifest)
            return json(
                notebook_response.model_dump(),
                200,
            )

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

            status = 200 if core.docker_image_exists(self.nb_config, image_url, internal_gitlab_user) else 404
            return HTTPResponse(status=status)

        return "/notebooks/images", ["GET"], _check_docker_image


@dataclass(kw_only=True)
class NotebooksNewBP(CustomBlueprint):
    """Handlers for manipulating notebooks for the new Amalthea operator."""

    authenticator: base_models.Authenticator
    internal_gitlab_authenticator: base_models.Authenticator
    nb_config: NotebooksConfig
    project_repo: ProjectRepository
    session_repo: SessionRepository
    rp_repo: ResourcePoolRepository
    storage_repo: StorageV2Repository

    def start(self) -> BlueprintFactoryResponse:
        """Start a session with the new operator."""

        @authenticate_2(self.authenticator, self.internal_gitlab_authenticator)
        @validate(json=apispec.SessionPostRequest)
        async def _handler(
            _: Request,
            user: AuthenticatedAPIUser | AnonymousAPIUser,
            internal_gitlab_user: APIUser,
            body: apispec.SessionPostRequest,
        ) -> JSONResponse:
            # gitlab_client = NotebooksGitlabClient(self.nb_config.git.url, internal_gitlab_user.access_token)
            launcher = await self.session_repo.get_launcher(user, ULID.from_str(body.launcher_id))
            project = await self.project_repo.get_project(user=user, project_id=launcher.project_id)
            server_name = renku_2_make_server_name(
                safe_username=user.id, project_id=str(launcher.project_id), launcher_id=body.launcher_id
            )
            existing_session = await self.nb_config.k8s_v2_client.get_server(server_name, user.id)
            if existing_session is not None and existing_session.spec is not None:
                return json(existing_session.as_apispec().model_dump(exclude_none=True, mode="json"))
            environment = launcher.environment
            image = environment.container_image
            default_resource_class = await self.rp_repo.get_default_resource_class()
            if default_resource_class.id is None:
                raise errors.ProgrammingError(message="The default resource class has to have an ID", quiet=True)
            resource_class_id = body.resource_class_id or default_resource_class.id
            await self.nb_config.crc_validator.validate_class_storage(user, resource_class_id, body.disk_storage)
            work_dir = environment.working_directory
            # user_secrets: K8sUserSecrets | None = None
            # if body.user_secrets:
            #     user_secrets = K8sUserSecrets(
            #         name=server_name,
            #         user_secret_ids=body.user_secrets.user_secret_ids,
            #         mount_path=body.user_secrets.mount_path,
            #     )
            cloud_storages_db = await self.storage_repo.get_storage(
                user=user, project_id=project.id, include_secrets=True
            )
            cloud_storage: dict[str, RCloneStorage] = {
                str(s.storage_id): RCloneStorage(
                    source_path=s.source_path,
                    mount_folder=(work_dir / s.target_path).as_posix(),
                    configuration=s.configuration.model_dump(mode="python"),
                    readonly=s.readonly,
                    config=self.nb_config,
                    name=s.name,
                )
                for s in cloud_storages_db
            }
            cloud_storage_request: dict[str, RCloneStorage] = {
                s.storage_id: RCloneStorage(
                    source_path=s.source_path,
                    mount_folder=(work_dir / s.target_path).as_posix(),
                    configuration=s.configuration,
                    readonly=s.readonly,
                    config=self.nb_config,
                    name=None,
                )
                for s in body.cloudstorage or []
            }
            # NOTE: Check the cloud storage in the request body and if any match
            # then overwrite the projects cloud storages
            # NOTE: Cloud storages in the session launch request body that are not form the DB will cause a 422 error
            for csr_id, csr in cloud_storage_request.items():
                if csr_id not in cloud_storage:
                    raise errors.MissingResourceError(
                        message=f"You have requested a cloud storage with ID {csr_id} which does not exist "
                        "or you dont have access to.",
                        quiet=True,
                    )
                cloud_storage[csr_id] = csr
            repositories = [Repository(url=i) for i in project.repositories]
            secrets_to_create: list[V1Secret] = []
            # Generate the cloud starge secrets
            data_sources: list[DataSource] = []
            for ics, cs in enumerate(cloud_storage.values()):
                secret_name = f"{server_name}-ds-{ics}"
                secrets_to_create.append(cs.secret(secret_name, self.nb_config.k8s_client.preferred_namespace))
                data_sources.append(
                    DataSource(mountPath=cs.mount_folder, secretRef=SecretRefWhole(name=secret_name, adopt=True))
                )
            cert_init, cert_vols = init_containers.certificates_container(self.nb_config)
            session_init_containers = [InitContainer.model_validate(self.nb_config.k8s_v2_client.sanitize(cert_init))]
            extra_volumes = [
                ExtraVolume.model_validate(self.nb_config.k8s_v2_client.sanitize(volume)) for volume in cert_vols
            ]
            if isinstance(user, AuthenticatedAPIUser):
                extra_volumes.append(
                    ExtraVolume(
                        name="renku-authorized-emails",
                        secret=SecretAsVolume(
                            secretName=server_name,
                            items=[SecretAsVolumeItem(key="authorized_emails", path="authorized_emails")],
                        ),
                    )
                )
            git_providers = await self.nb_config.git_provider_helper.get_providers(user=user)
            git_clone = await init_containers.git_clone_container_v2(
                user=user,
                config=self.nb_config,
                repositories=repositories,
                git_providers=git_providers,
                workspace_mount_path=launcher.environment.mount_directory,
                work_dir=launcher.environment.working_directory,
            )
            if git_clone is not None:
                session_init_containers.append(InitContainer.model_validate(git_clone))
            extra_containers: list[ExtraContainer] = []
            git_proxy_container = await git_proxy.main_container(
                user=user, config=self.nb_config, repositories=repositories, git_providers=git_providers
            )
            if git_proxy_container is not None:
                extra_containers.append(
                    ExtraContainer.model_validate(self.nb_config.k8s_v2_client.sanitize(git_proxy_container))
                )

            base_server_url = self.nb_config.sessions.ingress.base_url(server_name)
            base_server_path = self.nb_config.sessions.ingress.base_path(server_name)
            annotations: dict[str, str] = {
                "renku.io/project_id": str(launcher.project_id),
                "renku.io/launcher_id": body.launcher_id,
                "renku.io/resource_class_id": str(body.resource_class_id or default_resource_class.id),
            }
            manifest = AmaltheaSessionV1Alpha1(
                metadata=Metadata(name=server_name, annotations=annotations),
                spec=AmaltheaSessionSpec(
                    codeRepositories=[],
                    hibernated=False,
                    session=Session(
                        image=image,
                        urlPath=base_server_path,
                        port=environment.port,
                        storage=Storage(
                            className=self.nb_config.sessions.storage.pvs_storage_class,
                            size=str(body.disk_storage) + "G",
                            mountPath=environment.mount_directory.as_posix(),
                        ),
                        workingDir=environment.working_directory.as_posix(),
                        runAsUser=environment.uid,
                        runAsGroup=environment.gid,
                        resources=Resources(claims=None, requests=None, limits=None),
                        extraVolumeMounts=[],
                        command=environment.command,
                        args=environment.args,
                        shmSize="1G",
                        env=[
                            SessionEnvItem(name="RENKU_BASE_URL_PATH", value=base_server_path),
                            SessionEnvItem(name="RENKU_BASE_URL", value=base_server_url),
                        ],
                    ),
                    ingress=Ingress(
                        host=self.nb_config.sessions.ingress.host,
                        ingressClassName=self.nb_config.sessions.ingress.annotations.get("kubernetes.io/ingress.class"),
                        annotations=self.nb_config.sessions.ingress.annotations,
                        tlsSecret=TlsSecret(adopt=False, name=self.nb_config.sessions.ingress.tls_secret)
                        if self.nb_config.sessions.ingress.tls_secret is not None
                        else None,
                    ),
                    extraContainers=extra_containers,
                    initContainers=session_init_containers,
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
                        secretRef=SecretRefKey(name=server_name, key="auth", adopt=True),
                        extraVolumeMounts=[
                            ExtraVolumeMount(name="renku-authorized-emails", mountPath="/authorized_emails")
                        ]
                        if isinstance(user, AuthenticatedAPIUser)
                        else [],
                    ),
                    dataSources=data_sources,
                ),
            )
            parsed_proxy_url = urlparse(urljoin(base_server_url + "/", "oauth2"))
            secret_data = {}
            if isinstance(user, AuthenticatedAPIUser):
                secret_data["auth"] = dumps(
                    {
                        "provider": "oidc",
                        "client_id": self.nb_config.sessions.oidc.client_id,
                        "oidc_issuer_url": self.nb_config.sessions.oidc.issuer_url,
                        "session_cookie_minimal": True,
                        "skip_provider_button": True,
                        "redirect_url": urljoin(base_server_url + "/", "oauth2/callback"),
                        "cookie_path": base_server_path,
                        "proxy_prefix": parsed_proxy_url.path,
                        "authenticated_emails_file": "/authorized_emails/authorized_emails",
                        "client_secret": self.nb_config.sessions.oidc.client_secret,
                        "cookie_secret": base64.urlsafe_b64encode(os.urandom(32)).decode(),
                        "insecure_oidc_allow_unverified_email": self.nb_config.sessions.oidc.allow_unverified_email,
                    }
                )
                secret_data["authorized_emails"] = user.email
            else:
                secret_data["auth"] = safe_dump(
                    {
                        "token": user.id,
                        "cookie_key": "Renku-Auth-Anon-Id",
                        "verbose": True,
                    }
                )
            secrets_to_create.append(V1Secret(metadata=V1ObjectMeta(name=server_name), string_data=secret_data))
            for s in secrets_to_create:
                await self.nb_config.k8s_v2_client.create_secret(s)
            try:
                manifest = await self.nb_config.k8s_v2_client.create_server(manifest, user.id)
            except Exception:
                for s in secrets_to_create:
                    await self.nb_config.k8s_v2_client.delete_secret(s.metadata.name)
                raise errors.ProgrammingError(message="Could not start the amalthea session")

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
            session = await self.nb_config.k8s_v2_client.get_server(session_id, user.id)
            if session is None:
                raise errors.MissingResourceError(
                    message=f"The sesison with ID {session_id} does not exist", quiet=True
                )
            # TODO: Some patching should only be done when the session is in some states to avoid inadvertent restarts
            patches: dict[str, Any] = {}
            if body.resource_class_id is not None:
                rcs = await self.rp_repo.get_classes(user, id=body.resource_class_id)
                if len(rcs) == 0:
                    raise errors.MissingResourceError(
                        message=f"The resource class you requested with ID {body.resource_class_id} does not exist",
                        quiet=True,
                    )
                rc = rcs[0]
                patches |= dict(
                    spec=dict(
                        session=dict(
                            resources=dict(requests=dict(cpu=f"{round(rc.cpu * 1000)}m", memory=f"{rc.memory}Gi"))
                        )
                    )
                )
                # TODO: Add a config to specifiy the gpu kind, there is also GpuKind enum in reosurce_pools
                patches["spec"]["session"]["resources"]["requests"]["nvidia.com/gpu"] = rc.gpu
                # NOTE: K8s fails if the gpus limit is not equal to the requests because it cannot be overcommited
                patches["spec"]["session"]["resources"]["limits"] = {"nvidia.com/gpu": rc.gpu}
            if (
                body.state is not None
                and body.state.value.lower() == State.Hibernated.value.lower()
                and body.state.value.lower() != session.status.state.value.lower()
            ):
                if "spec" not in patches:
                    patches["spec"] = {}
                patches["spec"]["hibernated"] = True
            elif (
                body.state is not None
                and body.state.value.lower() == State.Running.value.lower()
                and session.status.state.value.lower() != body.state.value.lower()
            ):
                if "spec" not in patches:
                    patches["spec"] = {}
                patches["spec"]["hibernated"] = False

            if len(patches) > 0:
                new_session = await self.nb_config.k8s_v2_client.patch_server(session_id, user.id, patches)
            else:
                new_session = session

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
            parsed_image = Image.from_path(query.image_url)
            image_repo = parsed_image.repo_api()
            if parsed_image.hostname == self.nb_config.git.registry and internal_gitlab_user.access_token:
                image_repo = image_repo.with_oauth2_token(internal_gitlab_user.access_token)
            if await image_repo.image_exists(parsed_image):
                return HTTPResponse(status=200)
            else:
                return HTTPResponse(status=404)

        return "/sessions/images", ["GET"], _check_docker_image
