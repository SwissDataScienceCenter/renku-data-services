"""Notebooks service core implementation."""

from renku_data_services.base_models import AnonymousAPIUser, APIUser, AuthenticatedAPIUser
from renku_data_services.errors.errors import MissingResourceError
from renku_data_services.notebooks.api.classes.image import Image
from renku_data_services.notebooks.api.classes.server_manifest import UserServerManifest
from renku_data_services.notebooks.config import NotebooksConfig


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
        raise MissingResourceError(message=f"The server {server_name} does not exist.")
    return UserServerManifest(server, config.sessions.default_image)


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
