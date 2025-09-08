"""Notebooks service core implementation, specifically for JupyterServer sessions."""

import contextlib
import json as json_lib
from datetime import UTC, datetime
from math import floor
from pathlib import PurePosixPath
from typing import Any

import escapism
import httpx
from gitlab.const import Visibility as GitlabVisibility
from gitlab.v4.objects.projects import Project as GitlabProject
from sanic.response import JSONResponse
from ulid import ULID

from renku_data_services.app_config import logging
from renku_data_services.base_models import AnonymousAPIUser, APIUser, AuthenticatedAPIUser
from renku_data_services.base_models.validation import validated_json
from renku_data_services.errors import errors
from renku_data_services.notebooks import apispec
from renku_data_services.notebooks.api.classes.auth import GitlabToken, RenkuTokens
from renku_data_services.notebooks.api.classes.image import Image
from renku_data_services.notebooks.api.classes.repository import Repository
from renku_data_services.notebooks.api.classes.server import Renku1UserServer, UserServer
from renku_data_services.notebooks.api.classes.server_manifest import UserServerManifest
from renku_data_services.notebooks.api.classes.user import NotebooksGitlabClient
from renku_data_services.notebooks.api.schemas.cloud_storage import RCloneStorage
from renku_data_services.notebooks.api.schemas.secrets import K8sUserSecrets
from renku_data_services.notebooks.api.schemas.server_options import ServerOptions
from renku_data_services.notebooks.api.schemas.servers_get import NotebookResponse
from renku_data_services.notebooks.api.schemas.servers_patch import PatchServerStatusEnum
from renku_data_services.notebooks.config import NotebooksConfig
from renku_data_services.notebooks.constants import JUPYTER_SESSION_GVK
from renku_data_services.notebooks.errors import intermittent
from renku_data_services.notebooks.errors import user as user_errors
from renku_data_services.notebooks.util import repository
from renku_data_services.notebooks.util.kubernetes_ import find_container, renku_1_make_server_name
from renku_data_services.storage.db import StorageRepository
from renku_data_services.storage.models import CloudStorage
from renku_data_services.users.db import UserRepo

logger = logging.getLogger(__name__)


def notebooks_info(config: NotebooksConfig) -> dict:
    """Returns notebooks configuration information."""

    culling = config.sessions.culling
    info = {
        "name": "renku-notebooks",
        "versions": [
            {
                "version": config.version,
                "data": {
                    "anonymousSessionsEnabled": config.anonymous_sessions_enabled,
                    "cloudstorageEnabled": config.cloud_storage.enabled,
                    "cloudstorageClass": config.cloud_storage.storage_class,
                    "sshEnabled": config.ssh_enabled,
                    "defaultCullingThresholds": {
                        "registered": {
                            "idle": culling.registered.idle_seconds,
                            "hibernation": culling.registered.hibernated_seconds,
                        },
                        "anonymous": {
                            "idle": culling.anonymous.idle_seconds,
                            "hibernation": culling.anonymous.hibernated_seconds,
                        },
                    },
                },
            }
        ],
    }
    return info


async def user_servers(
    config: NotebooksConfig, user: AnonymousAPIUser | AuthenticatedAPIUser, filter_attrs: list[dict]
) -> dict[str, UserServerManifest]:
    """Returns a filtered list of servers for the given user."""

    servers = [
        UserServerManifest(s, config.sessions.default_image) for s in await config.k8s_client.list_sessions(user.id)
    ]
    filtered_servers = {}
    ann_prefix = config.session_get_endpoint_annotations.renku_annotation_prefix
    for server in servers:
        if all([server.annotations.get(f"{ann_prefix}{key}") == value for key, value in filter_attrs]):
            filtered_servers[server.server_name] = server
    return filtered_servers


async def user_server(
    config: NotebooksConfig, user: AnonymousAPIUser | AuthenticatedAPIUser, server_name: str
) -> UserServerManifest:
    """Returns the requested server for the user."""

    server = await config.k8s_client.get_session(server_name, user.id)
    if server is None:
        raise errors.MissingResourceError(message=f"The server {server_name} does not exist.")
    return UserServerManifest(server, config.sessions.default_image)


async def patch_server(
    config: NotebooksConfig,
    user: AnonymousAPIUser | AuthenticatedAPIUser,
    internal_gitlab_user: APIUser,
    server_name: str,
    patch_body: apispec.PatchServerRequest,
) -> UserServerManifest:
    """Applies patch to the given server."""

    if not config.sessions.storage.pvs_enabled:
        raise intermittent.PVDisabledError()

    server = await config.k8s_client.get_session(server_name, user.id)
    if server is None:
        raise errors.MissingResourceError(message=f"The server with name {server_name} cannot be found")
    if server.spec is None:
        raise errors.ProgrammingError(message="The server manifest is absent")

    new_server = server
    currently_hibernated = server.spec.jupyterServer.hibernated
    currently_failing = server.status.get("state", "running") == "failed"
    state = PatchServerStatusEnum.from_api_state(patch_body.state) if patch_body.state is not None else None
    resource_class_id = patch_body.resource_class_id
    if server and not (currently_hibernated or currently_failing) and resource_class_id:
        raise user_errors.UserInputError(
            message="The resource class can be changed only if the server is hibernated or failing"
        )

    if resource_class_id:
        parsed_server_options = await config.crc_validator.validate_class_storage(
            user,
            resource_class_id,
            storage=None,  # we do not care about validating storage
        )
        js_patch: list[dict[str, Any]] = [
            {
                "op": "replace",
                "path": "/spec/jupyterServer/resources",
                "value": parsed_server_options.to_k8s_resources(config.sessions.enforce_cpu_limits),
            },
            {
                "op": "replace",
                # NOTE: ~1 is how you escape '/' in json-patch
                "path": "/metadata/annotations/renku.io~1resourceClassId",
                "value": str(resource_class_id),
            },
        ]
        if parsed_server_options.priority_class:
            js_patch.append(
                {
                    "op": "replace",
                    # NOTE: ~1 is how you escape '/' in json-patch
                    "path": "/metadata/labels/renku.io~1quota",
                    "value": parsed_server_options.priority_class,
                }
            )
        elif server.metadata.labels.get("renku.io/quota"):
            js_patch.append(
                {
                    "op": "remove",
                    # NOTE: ~1 is how you escape '/' in json-patch
                    "path": "/metadata/labels/renku.io~1quota",
                }
            )
        new_server = await config.k8s_client.patch_session(
            session_name=server_name, safe_username=user.id, patch=js_patch
        )
        ss_patch: list[dict[str, Any]] = [
            {
                "op": "replace",
                "path": "/spec/template/spec/priorityClassName",
                "value": parsed_server_options.priority_class,
            }
        ]
        await config.k8s_client.patch_statefulset(session_name=server_name, safe_username=user.id, patch=ss_patch)

    if state == PatchServerStatusEnum.Hibernated:
        # NOTE: Do nothing if server is already hibernated
        currently_hibernated = server.spec.jupyterServer.hibernated
        if server and currently_hibernated:
            logger.warning(f"Server {server_name} is already hibernated.")

            return UserServerManifest(server, config.sessions.default_image)

        hibernation: dict[str, str | bool] = {"branch": "", "commit": "", "dirty": "", "synchronized": ""}

        sidecar_patch = find_container(server.spec.patches, "git-sidecar")
        status = (
            repository.get_status(
                server_name=server_name,
                access_token=user.access_token,
                hostname=config.sessions.ingress.host,
            )
            if sidecar_patch is not None
            else None
        )
        if status:
            hibernation = {
                "branch": status.get("branch", ""),
                "commit": status.get("commit", ""),
                "dirty": not status.get("clean", True),
                "synchronized": status.get("ahead", 0) == status.get("behind", 0) == 0,
            }

        hibernation["date"] = datetime.now(UTC).isoformat(timespec="seconds")

        patch = {
            "metadata": {
                "annotations": {
                    "renku.io/hibernation": json_lib.dumps(hibernation),
                    "renku.io/hibernationBranch": hibernation["branch"],
                    "renku.io/hibernationCommitSha": hibernation["commit"],
                    "renku.io/hibernationDirty": str(hibernation["dirty"]).lower(),
                    "renku.io/hibernationSynchronized": str(hibernation["synchronized"]).lower(),
                    "renku.io/hibernationDate": hibernation["date"],
                },
            },
            "spec": {
                "jupyterServer": {
                    "hibernated": True,
                },
            },
        }

        new_server = await config.k8s_client.patch_session(session_name=server_name, safe_username=user.id, patch=patch)
    elif state == PatchServerStatusEnum.Running:
        # NOTE: We clear hibernation annotations in Amalthea to avoid flickering in the UI (showing
        # the repository as dirty when resuming a session for a short period of time).
        patch = {
            "spec": {
                "jupyterServer": {
                    "hibernated": False,
                },
            },
        }
        # NOTE: The tokens in the session could expire if the session is hibernated long enough,
        # here we inject new ones to make sure everything is valid when the session starts back up.
        if user.access_token is None or user.refresh_token is None or internal_gitlab_user.access_token is None:
            raise errors.UnauthorizedError(message="Cannot patch the server if the user is not fully logged in.")
        renku_tokens = RenkuTokens(access_token=user.access_token, refresh_token=user.refresh_token)
        gitlab_token = GitlabToken(
            access_token=internal_gitlab_user.access_token,
            expires_at=(
                floor(user.access_token_expires_at.timestamp()) if user.access_token_expires_at is not None else -1
            ),
        )
        await config.k8s_client.patch_session_tokens(server_name, user.id, renku_tokens, gitlab_token)
        new_server = await config.k8s_client.patch_session(session_name=server_name, safe_username=user.id, patch=patch)

    return UserServerManifest(new_server, config.sessions.default_image)


async def stop_server(config: NotebooksConfig, user: AnonymousAPIUser | AuthenticatedAPIUser, server_name: str) -> None:
    """Stops / deletes the requested server."""

    await config.k8s_client.delete_session(server_name, safe_username=user.id)


def server_options(config: NotebooksConfig) -> dict:
    """Returns the server's options configured."""

    return {
        **config.server_options.ui_choices,
        "cloudstorage": {
            "enabled": config.cloud_storage.enabled,
        },
    }


async def server_logs(
    config: NotebooksConfig, user: AnonymousAPIUser | AuthenticatedAPIUser, server_name: str, max_lines: int
) -> dict:
    """Returns the logs of the given server."""

    return await config.k8s_client.get_session_logs(
        session_name=server_name,
        safe_username=user.id,
        max_log_lines=max_lines,
    )


async def docker_image_exists(config: NotebooksConfig, image_url: str, internal_gitlab_user: APIUser) -> bool:
    """Returns whether the passed docker image url exists.

    If the user is logged in the internal GitLab (Renku V1), set the
    credentials for the check.
    """

    parsed_image = Image.from_path(image_url)
    image_repo = parsed_image.repo_api().maybe_with_oauth2_token(config.git.registry, internal_gitlab_user.access_token)
    return await image_repo.image_exists(parsed_image)


async def docker_image_workdir(
    config: NotebooksConfig, image_url: str, internal_gitlab_user: APIUser
) -> PurePosixPath | None:
    """Returns the working directory for the image.

    If the user is logged in the internal GitLab (Renku V1), set the
    credentials for the check.
    """

    parsed_image = Image.from_path(image_url)
    image_repo = parsed_image.repo_api().maybe_with_oauth2_token(config.git.registry, internal_gitlab_user.access_token)
    return await image_repo.image_workdir(parsed_image)


async def launch_notebook_helper(
    nb_config: NotebooksConfig,
    server_name: str,
    server_class: type[UserServer],
    user: AnonymousAPIUser | AuthenticatedAPIUser,
    image: str | None,
    resource_class_id: int | None,
    storage: int | None,
    environment_variables: dict[str, str],
    user_secrets: apispec.UserSecrets | None,
    default_url: str,
    lfs_auto_fetch: bool,
    cloudstorage: list[apispec.RCloneStorageRequest],
    server_options: ServerOptions | dict | None,
    gl_namespace: str | None,  # Renku 1.0
    project: str | None,  # Renku 1.0
    branch: str | None,  # Renku 1.0
    commit_sha: str | None,  # Renku 1.0
    gl_project: GitlabProject | None,  # Renku 1.0
    gl_project_path: str | None,  # Renku 1.0
    repositories: list[apispec.LaunchNotebookRequestRepository] | None,  # Renku 2.0
    internal_gitlab_user: APIUser,
    user_repo: UserRepo,
    storage_repo: StorageRepository,
) -> tuple[UserServerManifest, int]:
    """Helper function to launch a Jupyter server."""

    server = await nb_config.k8s_client.get_session(server_name, user.id)

    if server:
        return UserServerManifest(server, nb_config.sessions.default_image, nb_config.sessions.storage.pvs_enabled), 200

    if not nb_config.v1_sessions_enabled:
        raise errors.ForbiddenError(message="Starting v1 sessions is not allowed.")

    gl_project_path = gl_project_path if gl_project_path is not None else ""

    # Add annotation for old and new notebooks
    is_image_private = False
    using_default_image = False
    if image:
        # A specific image was requested
        parsed_image = Image.from_path(image)
        image_repo = parsed_image.repo_api()
        image_exists_publicly = await image_repo.image_exists(parsed_image)
        image_exists_privately = False
        if (
            not image_exists_publicly
            and parsed_image.hostname == nb_config.git.registry
            and internal_gitlab_user.access_token
        ):
            image_repo = image_repo.with_oauth2_token(internal_gitlab_user.access_token)
            image_exists_privately = await image_repo.image_exists(parsed_image)
        if not image_exists_privately and not image_exists_publicly:
            using_default_image = True
            image = nb_config.sessions.default_image
            parsed_image = Image.from_path(image)
        if image_exists_privately:
            is_image_private = True
    elif gl_project is not None:
        # An image was not requested specifically, use the one automatically built for the commit
        if commit_sha is None:
            raise errors.ValidationError(
                message="Cannot run a session with an image based on a commit sha if the commit sha is not known."
            )
        image = f"{nb_config.git.registry}/{gl_project.path_with_namespace.lower()}:{commit_sha[:7]}"
        parsed_image = Image(
            nb_config.git.registry,
            gl_project.path_with_namespace.lower(),
            commit_sha[:7],
        )
        # NOTE: a project pulled from the Gitlab API without credentials has no visibility attribute
        # and by default it can only be public since only public projects are visible to
        # non-authenticated users. Also, a nice footgun from the Gitlab API Python library.
        is_image_private = getattr(gl_project, "visibility", GitlabVisibility.PUBLIC) != GitlabVisibility.PUBLIC
        image_repo = parsed_image.repo_api().maybe_with_oauth2_token(
            nb_config.git.registry, internal_gitlab_user.access_token
        )
        if not await image_repo.image_exists(parsed_image):
            raise errors.MissingResourceError(
                message=(
                    f"Cannot start the session because the following the image {image} does not "
                    "exist or the user does not have the permissions to access it."
                )
            )
    else:
        raise user_errors.UserInputError(message="Cannot determine which Docker image to use.")

    host = nb_config.sessions.ingress.host
    parsed_server_options: ServerOptions | None = None
    session_namespace = nb_config.k8s.renku_namespace
    if resource_class_id is not None:
        # A resource class ID was passed in, validate with CRC service
        parsed_server_options = await nb_config.crc_validator.validate_class_storage(user, resource_class_id, storage)
        cluster = await nb_config.k8s_client.cluster_by_class_id(resource_class_id, user)
        session_namespace = cluster.namespace
        with contextlib.suppress(errors.MissingResourceError):
            (_, _, _, host, _, _) = (await nb_config.cluster_rp.select(cluster.id)).get_ingress_parameters(server_name)

    elif server_options is not None:
        if isinstance(server_options, dict):
            requested_server_options = ServerOptions(
                memory=server_options["mem_request"],
                storage=server_options["disk_request"],
                cpu=server_options["cpu_request"],
                gpu=server_options["gpu_request"],
                lfs_auto_fetch=server_options["lfs_auto_fetch"],
                default_url=server_options["defaultUrl"],
            )
        elif isinstance(server_options, ServerOptions):
            requested_server_options = server_options
        else:
            raise errors.ProgrammingError(
                message=f"Got an unexpected type of server options when launching sessions: {type(server_options)}"
            )
        # The old style API was used, try to find a matching class from the CRC service
        parsed_server_options = await nb_config.crc_validator.find_acceptable_class(user, requested_server_options)
        if parsed_server_options is None:
            raise user_errors.UserInputError(
                message="Cannot find suitable server options based on your request and the available resource classes.",
                detail="You are receiving this error because you are using the old API for "
                "selecting resources. Updating to the new API which includes specifying only "
                "a specific resource class ID and storage is preferred and more convenient.",
            )
    else:
        # No resource class ID specified or old-style server options, use defaults from CRC
        default_resource_class = await nb_config.crc_validator.get_default_class()
        max_storage_gb = default_resource_class.max_storage
        if storage is not None and storage > max_storage_gb:
            raise user_errors.UserInputError(
                message="The requested storage amount is higher than the "
                f"allowable maximum for the default resource class of {max_storage_gb}GB."
            )
        if storage is None:
            storage = default_resource_class.default_storage
        parsed_server_options = ServerOptions.from_resource_class(default_resource_class)
        # Storage in request is in GB
        parsed_server_options.set_storage(storage, gigabytes=True)

    if default_url is not None:
        parsed_server_options.default_url = default_url

    if lfs_auto_fetch is not None:
        parsed_server_options.lfs_auto_fetch = lfs_auto_fetch

    image_work_dir = await image_repo.image_workdir(parsed_image) or PurePosixPath("/")
    mount_path = image_work_dir / "work"

    server_work_dir = mount_path / gl_project_path

    storages: list[RCloneStorage] = []
    if cloudstorage:
        user_secret_key = await user_repo.get_or_create_user_secret_key(user)
        try:
            for cstorage in cloudstorage:
                saved_storage: CloudStorage | None = None
                if cstorage.storage_id:
                    saved_storage = await storage_repo.get_storage_by_id(ULID.from_str(cstorage.storage_id), user)
                storages.append(
                    await RCloneStorage.storage_from_schema(
                        data=cstorage.model_dump(),
                        work_dir=server_work_dir,
                        user_secret_key=user_secret_key,
                        saved_storage=saved_storage,
                        storage_class=nb_config.cloud_storage.storage_class,
                    )
                )
        except errors.ValidationError as e:
            raise user_errors.UserInputError(message=f"Couldn't load cloud storage config: {str(e)}") from e
        mount_points = set(s.mount_folder for s in storages if s.mount_folder and s.mount_folder != "/")
        if len(mount_points) != len(storages):
            raise user_errors.UserInputError(
                "Storage mount points must be set, can't be at the root of the project and must be unique."
            )
        if any(s1.mount_folder.startswith(s2.mount_folder) for s1 in storages for s2 in storages if s1 != s2):
            raise user_errors.UserInputError(
                message="Cannot mount a cloud storage into the mount point of another cloud storage."
            )

    repositories = repositories or []

    k8s_user_secret = None
    if user_secrets:
        k8s_user_secret = K8sUserSecrets(f"{server_name}-secret", **user_secrets.model_dump())

    # Renku 1-only parameters
    extra_kwargs: dict = dict(
        commit_sha=commit_sha,
        branch=branch,
        project=project,
        gl_namespace=gl_namespace,
        internal_gitlab_user=internal_gitlab_user,
        gitlab_project=gl_project,
    )
    server = server_class(
        user=user,
        image=image,
        server_name=server_name,
        server_options=parsed_server_options,
        environment_variables=environment_variables,
        user_secrets=k8s_user_secret,
        cloudstorage=storages,
        k8s_client=nb_config.k8s_client,
        workspace_mount_path=mount_path,
        work_dir=server_work_dir,
        using_default_image=using_default_image,
        is_image_private=is_image_private,
        repositories=[Repository.from_dict(r.model_dump()) for r in repositories],
        config=nb_config,
        host=host,
        namespace=session_namespace,
        **extra_kwargs,
    )

    if len(server.safe_username) > 63:
        raise user_errors.UserInputError(
            message="A username cannot be longer than 63 characters, "
            f"your username is {len(server.safe_username)} characters long.",
            detail="This can occur if your username has been changed manually or by an admin.",
        )

    manifest = await server.start()
    if manifest is None:
        raise errors.ProgrammingError(message="Failed to start server.")

    logger.debug(f"Server {server.server_name} has been started")

    owner_reference = {
        "apiVersion": JUPYTER_SESSION_GVK.group_version,
        "kind": JUPYTER_SESSION_GVK.kind,
        "name": server.server_name,
        "uid": manifest.metadata.uid,
    }

    async def create_secret(payload: dict[str, Any], type_message: str) -> None:
        async def _on_error(server_name: str, error_msg: str) -> None:
            await nb_config.k8s_client.delete_session(server_name, safe_username=user.id)
            raise RuntimeError(error_msg)

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    nb_config.user_secrets.secrets_storage_service_url + "/api/secrets/kubernetes",
                    json=payload,
                    headers={"Authorization": f"bearer {user.access_token}"},
                )
        except httpx.ConnectError as exc:
            await _on_error(server_name, f"{type_message} storage service could not be contacted {exc}")
        else:
            if response.status_code != 201:
                await _on_error(server_name, f"{type_message} could not be created {response.json()}")

    if k8s_user_secret is not None:
        request_data: dict[str, Any] = {
            "name": k8s_user_secret.name,
            "namespace": server.k8s_namespace(),
            "secret_ids": [str(id_) for id_ in k8s_user_secret.user_secret_ids],
            "owner_references": [owner_reference],
        }
        await create_secret(payload=request_data, type_message="User secrets")

    # NOTE: Create a secret for each storage that has saved secrets
    for icloud_storage, cloud_storage in enumerate(storages):
        if cloud_storage.secrets and cloud_storage.base_name:
            base_name = cloud_storage.base_name
            if not base_name:
                base_name = f"{server_name}-ds-{icloud_storage}"
            request_data = {
                "name": f"{base_name}-secrets",
                "namespace": server.k8s_namespace(),
                "secret_ids": list(cloud_storage.secrets.keys()),
                "owner_references": [owner_reference],
                "key_mapping": cloud_storage.secrets,
            }
            await create_secret(payload=request_data, type_message="Saved storage secrets")

    return UserServerManifest(manifest, nb_config.sessions.default_image), 201


async def launch_notebook(
    config: NotebooksConfig,
    user: AnonymousAPIUser | AuthenticatedAPIUser,
    internal_gitlab_user: APIUser,
    launch_request: apispec.LaunchNotebookRequestOld,
    user_repo: UserRepo,
    storage_repo: StorageRepository,
) -> tuple[UserServerManifest, int]:
    """Starts a server using the old operator."""

    cluster = await config.k8s_client.cluster_by_class_id(launch_request.resource_class_id, user)

    if isinstance(user, AnonymousAPIUser):
        safe_username = escapism.escape(user.id, escape_char="-").lower()
    else:
        safe_username = escapism.escape(user.email, escape_char="-").lower()
    server_name = renku_1_make_server_name(
        safe_username,
        launch_request.namespace,
        launch_request.project,
        launch_request.branch,
        launch_request.commit_sha,
        str(cluster.id),
    )
    project_slug = f"{launch_request.namespace}/{launch_request.project}"
    gitlab_client = NotebooksGitlabClient(config.git.url, internal_gitlab_user.access_token)
    gl_project = gitlab_client.get_renku_project(project_slug)
    if gl_project is None:
        raise errors.MissingResourceError(message=f"Cannot find gitlab project with slug {project_slug}")
    gl_project_path = gl_project.path
    server_class = Renku1UserServer
    _server_options = (
        ServerOptions.from_server_options_request_schema(
            launch_request.serverOptions.model_dump(),
            config.server_options.default_url_default,
            config.server_options.lfs_auto_fetch_default,
        )
        if launch_request.serverOptions is not None
        else None
    )

    return await launch_notebook_helper(
        nb_config=config,
        server_name=server_name,
        server_class=server_class,
        user=user,
        image=launch_request.image,
        resource_class_id=launch_request.resource_class_id,
        storage=launch_request.storage,
        environment_variables=launch_request.environment_variables,
        user_secrets=launch_request.user_secrets,
        default_url=launch_request.default_url,
        lfs_auto_fetch=launch_request.lfs_auto_fetch,
        cloudstorage=launch_request.cloudstorage,
        server_options=_server_options,
        gl_namespace=launch_request.namespace,
        project=launch_request.project,
        branch=launch_request.branch,
        commit_sha=launch_request.commit_sha,
        gl_project=gl_project,
        gl_project_path=gl_project_path,
        repositories=None,
        internal_gitlab_user=internal_gitlab_user,
        user_repo=user_repo,
        storage_repo=storage_repo,
    )


def serialize_v1_server(manifest: UserServerManifest, nb_config: NotebooksConfig, status: int = 200) -> JSONResponse:
    """Format and serialize a Renku v1 JupyterServer manifest."""
    data = NotebookResponse().dump(NotebookResponse.format_user_pod_data(manifest, nb_config))
    return validated_json(apispec.NotebookResponse, data, status=status, model_dump_kwargs=dict(by_alias=True))


def serialize_v1_servers(
    manifests: dict[str, UserServerManifest], nb_config: NotebooksConfig, status: int = 200
) -> JSONResponse:
    """Format and serialize many Renku v1 JupyterServer manifests."""
    data = {
        manifest.server_name: NotebookResponse().dump(NotebookResponse.format_user_pod_data(manifest, nb_config))
        for manifest in sorted(manifests.values(), key=lambda x: x.server_name)
    }
    return validated_json(
        apispec.ServersGetResponse, {"servers": data}, status=status, model_dump_kwargs=dict(by_alias=True)
    )
