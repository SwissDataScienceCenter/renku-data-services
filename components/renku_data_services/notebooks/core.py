"""Notebooks service core implementation."""

import json as json_lib
from datetime import UTC, datetime
from math import floor
from typing import Any

from sanic.log import logger

from renku_data_services.base_models import AnonymousAPIUser, APIUser, AuthenticatedAPIUser
from renku_data_services.errors import errors
from renku_data_services.notebooks import apispec
from renku_data_services.notebooks.api.classes.auth import GitlabToken, RenkuTokens
from renku_data_services.notebooks.api.classes.image import Image
from renku_data_services.notebooks.api.classes.server_manifest import UserServerManifest
from renku_data_services.notebooks.api.schemas.servers_patch import PatchServerStatusEnum
from renku_data_services.notebooks.config import NotebooksConfig
from renku_data_services.notebooks.errors import intermittent
from renku_data_services.notebooks.errors import user as user_errors
from renku_data_services.notebooks.util import repository
from renku_data_services.notebooks.util.kubernetes_ import find_container


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
) -> dict:
    """Returns a filtered list of servers for the given user."""

    servers = [
        UserServerManifest(s, config.sessions.default_image) for s in await config.k8s_client.list_servers(user.id)
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

    server = await config.k8s_client.get_server(server_name, user.id)
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

    server = await config.k8s_client.get_server(server_name, user.id)
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
            "The resource class can be changed only if the server is hibernated or failing"
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
        new_server = await config.k8s_client.patch_server(
            server_name=server_name, safe_username=user.id, patch=js_patch
        )
        ss_patch: list[dict[str, Any]] = [
            {
                "op": "replace",
                "path": "/spec/template/spec/priorityClassName",
                "value": parsed_server_options.priority_class,
            }
        ]
        await config.k8s_client.patch_statefulset(server_name=server_name, patch=ss_patch)

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

        new_server = await config.k8s_client.patch_server(server_name=server_name, safe_username=user.id, patch=patch)
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
        await config.k8s_client.patch_tokens(server_name, renku_tokens, gitlab_token)
        new_server = await config.k8s_client.patch_server(server_name=server_name, safe_username=user.id, patch=patch)

    return UserServerManifest(new_server, config.sessions.default_image)


async def stop_server(
    config: NotebooksConfig, user: AnonymousAPIUser | AuthenticatedAPIUser, server_name: str
) -> None:
    """Stops / deletes the requested server."""

    await config.k8s_client.delete_server(server_name, safe_username=user.id)


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

    return await config.k8s_client.get_server_logs(
        server_name=server_name,
        safe_username=user.id,
        max_log_lines=max_lines,
    )


def docker_image_exists(config: NotebooksConfig, image_url: str, internal_gitlab_user: APIUser) -> bool:
    """Returns whether the passed docker image url exists.

    If the user is logged in the internal GitLab (Renku V1), set the
    credentials for the check.
    """

    parsed_image = Image.from_path(image_url)
    image_repo = parsed_image.repo_api()
    if parsed_image.hostname == config.git.registry and internal_gitlab_user.access_token:
        image_repo = image_repo.with_oauth2_token(internal_gitlab_user.access_token)
    return image_repo.image_exists(parsed_image)
