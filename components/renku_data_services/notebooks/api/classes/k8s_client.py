"""An abstraction over the kr8s kubernetes client and the k8s-watcher."""

import base64
import json
from contextlib import suppress
from typing import Any, Generic, Optional, TypeVar, cast

import httpx
from box import Box
from kr8s import NotFoundError, ServerError
from kr8s.asyncio.objects import APIObject, Pod, Secret, StatefulSet
from kubernetes.client import ApiClient, V1Secret

from renku_data_services.errors import errors
from renku_data_services.k8s_watcher.db import CachedK8sClient
from renku_data_services.k8s_watcher.models import ClusterId, K8sObject, K8sObjectMeta, ListFilter
from renku_data_services.notebooks.api.classes.auth import GitlabToken, RenkuTokens
from renku_data_services.notebooks.crs import AmaltheaSessionV1Alpha1, JupyterServerV1Alpha1
from renku_data_services.notebooks.errors.programming import ProgrammingError
from renku_data_services.notebooks.util.kubernetes_ import find_env_var

sanitize_for_serialization = ApiClient().sanitize_for_serialization


# NOTE The type ignore below is because the kr8s library has no type stubs, they claim pyright better handles type hints
class JupyterServerV1Alpha1Kr8s(APIObject):
    """Spec for jupyter servers used by the k8s client."""

    kind: str = "JupyterServer"
    version: str = "amalthea.dev/v1alpha1"
    namespaced: bool = True
    plural: str = "jupyterservers"
    singular: str = "jupyterserver"
    scalable: bool = False
    endpoint: str = "jupyterservers"


_SessionType = TypeVar("_SessionType", JupyterServerV1Alpha1, AmaltheaSessionV1Alpha1)


class K8sClient(Generic[_SessionType]):
    """The K8s client that combines a namespaced client and a jupyter server cache."""

    def __init__(
        self,
        cached_client: CachedK8sClient,
        username_label: str,
        namespace: str,
        cluster: ClusterId,
        server_type: type[_SessionType],
    ):
        self.cached_client: CachedK8sClient = cached_client
        self.username_label = username_label
        self.namespace = namespace
        self.cluster = cluster
        self.server_type: type[_SessionType] = server_type
        if not self.username_label:
            raise ProgrammingError("username_label has to be provided to K8sClient")

    async def list_servers(self, safe_username: str) -> list[_SessionType]:
        """Get a list of servers that belong to a user.

        Attempt to use the cache first but if the cache fails then use the k8s API.
        """
        return [
            self.server_type.model_validate(s.manifest)
            async for s in self.cached_client.list(
                ListFilter(
                    kind=self.server_type.kind,
                    version=self.server_type.apiVersion,
                    user_id=safe_username,
                    label_selector={self.username_label: safe_username},
                    namespace=self.namespace,
                )
            )
        ]

    async def get_server(self, name: str, safe_username: str) -> _SessionType | None:
        """Attempt to get a specific server by name from the cache.

        If the request to the cache fails, fallback to the k8s API.
        """
        server = await self.cached_client.get(
            K8sObjectMeta(
                kind=self.server_type.kind,
                version=self.server_type.apiVersion,
                user_id=safe_username,
                name=name,
                namespace=self.namespace,
                cluster=self.cluster,
            )
        )
        if server is None:
            return None
        server = self.server_type.model_validate(server.manifest)

        # NOTE: only the user that the server belongs to can read it, without the line
        # below anyone can request and read any one else's server
        if server and server.metadata and server.metadata.labels.get(self.username_label) != safe_username:
            return None
        return server

    async def get_server_logs(
        self, server_name: str, safe_username: str, max_log_lines: Optional[int] = None
    ) -> dict[str, str]:
        """Get the logs from the server."""
        # NOTE: this get_server ensures the user has access to the server without it you could read someone elses logs
        server = await self.get_server(server_name, safe_username)
        if not server:
            raise errors.MissingResourceError(
                message=f"Cannot find server {server_name} for user {safe_username} to retrieve logs."
            )
        pod_name = f"{server_name}-0"
        # TODO: implement a way to get this from the cache client
        result = await self.cached_client.get_api_object(
            K8sObjectMeta(
                name=pod_name, namespace=self.namespace, cluster=self.cluster, kind=Pod.kind, version=Pod.version
            )
        )
        logs: dict[str, str] = {}
        if result is None:
            return logs
        pod = result.obj
        assert isinstance(pod, Pod)
        containers = [container.name for container in pod.spec.containers + pod.spec.get("initContainers", [])]
        for container in containers:
            try:
                # NOTE: calling pod.logs without a container name set crashes the library
                clogs: list[str] = [clog async for clog in pod.logs(container=container, tail_lines=max_log_lines)]
            except httpx.ResponseNotRead:
                # NOTE: This occurs when the container is still starting but we try to read its logs
                continue
            except NotFoundError:
                raise errors.MissingResourceError(message=f"The pod {pod_name} does not exist.")
            except ServerError as err:
                if err.response is not None and err.response.status_code == 404:
                    raise errors.MissingResourceError(message=f"The pod {pod_name} does not exist.")
                raise
            else:
                logs[container] = "\n".join(clogs)
        return logs

    async def _get_secret(self, name: str) -> Secret | None:
        """Get a specific secret."""
        result = await self.cached_client.get_api_object(
            K8sObjectMeta(
                name=name, namespace=self.namespace, cluster=self.cluster, kind=Secret.kind, version=Secret.version
            )
        )
        if result is None:
            return None
        secret = result.obj
        assert isinstance(secret, Secret)
        return secret

    async def create_server(self, manifest: _SessionType, safe_username: str) -> _SessionType:
        """Create a server."""
        server_name = manifest.metadata.name
        server = await self.get_server(server_name, safe_username)
        if server:
            # NOTE: server already exists
            return server
        manifest.metadata.labels[self.username_label] = safe_username
        result = await self.cached_client.create(
            K8sObject(
                name=server_name,
                namespace=self.namespace,
                cluster=self.cluster,
                kind=self.server_type.kind,
                version=self.server_type.apiVersion,
                user_id=safe_username,
                manifest=Box(manifest),
            )
        )
        return self.server_type.model_validate(result.manifest)

    async def patch_server(
        self, server_name: str, safe_username: str, patch: dict[str, Any] | list[dict[str, Any]]
    ) -> _SessionType:
        """Patch a server."""
        server = await self.cached_client.get(
            K8sObjectMeta(
                kind=self.server_type.kind,
                version=self.server_type.apiVersion,
                user_id=safe_username,
                name=server_name,
                namespace=self.namespace,
                cluster=self.cluster,
            )
        )
        if not server:
            raise errors.MissingResourceError(
                message=f"Cannot find server {server_name} for user {safe_username} in order to patch it."
            )
        result = await self.cached_client.patch(server, patch=patch)
        return self.server_type.model_validate(result.manifest)

    async def patch_statefulset(
        self, server_name: str, patch: dict[str, Any] | list[dict[str, Any]]
    ) -> StatefulSet | None:
        """Patch a statefulset."""
        sts = await self.cached_client.get_api_object(
            K8sObjectMeta(
                name=server_name,
                namespace=self.namespace,
                cluster=self.cluster,
                kind=StatefulSet.kind,
                version=StatefulSet.version,
            )
        )
        if sts is None:
            return None
        assert isinstance(sts, StatefulSet)
        await sts.obj.patch(patch=patch)

        return sts

    async def delete_server(self, server_name: str, safe_username: str) -> None:
        """Delete the server."""
        return await self.cached_client.delete(
            K8sObjectMeta(
                kind=self.server_type.kind,
                version=self.server_type.apiVersion,
                user_id=safe_username,
                name=server_name,
                namespace=self.namespace,
                cluster=self.cluster,
            )
        )

    async def patch_tokens(self, server_name: str, renku_tokens: RenkuTokens, gitlab_token: GitlabToken) -> None:
        """Patch the Renku and Gitlab access tokens used in a session."""
        sts = await self.cached_client.get_api_object(
            K8sObjectMeta(
                name=server_name,
                namespace=self.namespace,
                cluster=self.cluster,
                kind=StatefulSet.kind,
                version=StatefulSet.version,
            )
        )
        if sts is None:
            return None
        assert isinstance(sts, StatefulSet)
        patches = self._get_statefulset_token_patches(sts, renku_tokens)
        await sts.patch(patch=patches, type="json")
        await self.patch_image_pull_secret(server_name, gitlab_token)

    async def patch_image_pull_secret(self, server_name: str, gitlab_token: GitlabToken) -> None:
        """Patch the image pull secret used in a Renku session."""
        secret_name = f"{server_name}-image-secret"
        result = await self.cached_client.get_api_object(
            K8sObjectMeta(
                name=secret_name,
                namespace=self.namespace,
                cluster=self.cluster,
                kind=Secret.kind,
                version=Secret.version,
            )
        )
        if result is None:
            return None
        secret = result.obj
        assert isinstance(secret, Secret)

        secret_data = secret.data.to_dict()
        old_docker_config = json.loads(base64.b64decode(secret_data[".dockerconfigjson"]).decode())
        hostname = next(iter(old_docker_config["auths"].keys()), None)
        if not hostname:
            raise ProgrammingError(
                "Failed to refresh the access credentials in the image pull secret.",
                detail="Please contact a Renku administrator.",
            )
        new_docker_config = {
            "auths": {
                hostname: {
                    "Username": "oauth2",
                    "Password": gitlab_token.access_token,
                    "Email": old_docker_config["auths"][hostname]["Email"],
                }
            }
        }
        patch_path = "/data/.dockerconfigjson"
        patch = [
            {
                "op": "replace",
                "path": patch_path,
                "value": base64.b64encode(json.dumps(new_docker_config).encode()).decode(),
            }
        ]
        await secret.patch(patch, type="json")

    @staticmethod
    def _get_statefulset_token_patches(sts: StatefulSet, renku_tokens: RenkuTokens) -> list[dict[str, str]]:
        """Patch the Renku and Gitlab access tokens that are used in the session statefulset."""
        containers = cast(list[Box], sts.spec.template.spec.containers)
        init_containers = cast(list[Box], sts.spec.template.spec.initContainers)

        git_proxy_container_index, git_proxy_container = next(
            ((i, c) for i, c in enumerate(containers) if c.name == "git-proxy"),
            (None, None),
        )
        git_clone_container_index, git_clone_container = next(
            ((i, c) for i, c in enumerate(init_containers) if c.name == "git-clone"),
            (None, None),
        )
        secrets_container_index, secrets_container = next(
            ((i, c) for i, c in enumerate(init_containers) if c.name == "init-user-secrets"),
            (None, None),
        )

        def _get_env(container: Box) -> list[Box]:
            return cast(list[Box], container.env)

        git_proxy_renku_access_token_env = (
            find_env_var(_get_env(git_proxy_container), "GIT_PROXY_RENKU_ACCESS_TOKEN")
            if git_proxy_container is not None
            else None
        )
        git_proxy_renku_refresh_token_env = (
            find_env_var(_get_env(git_proxy_container), "GIT_PROXY_RENKU_REFRESH_TOKEN")
            if git_proxy_container is not None
            else None
        )
        git_clone_renku_access_token_env = (
            find_env_var(_get_env(git_clone_container), "GIT_CLONE_USER__RENKU_TOKEN")
            if git_clone_container is not None
            else None
        )
        secrets_renku_access_token_env = (
            find_env_var(_get_env(secrets_container), "RENKU_ACCESS_TOKEN") if secrets_container is not None else None
        )

        patches = list()
        if git_proxy_container_index is not None and git_proxy_renku_access_token_env is not None:
            patches.append(
                {
                    "op": "replace",
                    "path": (
                        f"/spec/template/spec/containers/{git_proxy_container_index}"
                        f"/env/{git_proxy_renku_access_token_env[0]}/value"
                    ),
                    "value": renku_tokens.access_token,
                }
            )
        if git_proxy_container_index is not None and git_proxy_renku_refresh_token_env is not None:
            patches.append(
                {
                    "op": "replace",
                    "path": (
                        f"/spec/template/spec/containers/{git_proxy_container_index}"
                        f"/env/{git_proxy_renku_refresh_token_env[0]}/value"
                    ),
                    "value": renku_tokens.refresh_token,
                },
            )
        if git_clone_container_index is not None and git_clone_renku_access_token_env is not None:
            patches.append(
                {
                    "op": "replace",
                    "path": (
                        f"/spec/template/spec/initContainers/{git_clone_container_index}"
                        f"/env/{git_clone_renku_access_token_env[0]}/value"
                    ),
                    "value": renku_tokens.access_token,
                },
            )
        if secrets_container_index is not None and secrets_renku_access_token_env is not None:
            patches.append(
                {
                    "op": "replace",
                    "path": (
                        f"/spec/template/spec/initContainers/{secrets_container_index}"
                        f"/env/{secrets_renku_access_token_env[0]}/value"
                    ),
                    "value": renku_tokens.access_token,
                },
            )

        return patches

    @property
    def preferred_namespace(self) -> str:
        """Get the preferred namespace for creating jupyter servers."""
        return self.namespace

    async def create_secret(self, secret: V1Secret) -> V1Secret:
        """Create a secret."""
        assert secret.metadata is not None
        result = await self.cached_client.create(
            K8sObject(
                name=secret.metadata.name,
                namespace=self.namespace,
                cluster=self.cluster,
                kind=Secret.kind,
                version=Secret.version,
                manifest=Box(secret.to_dict()),
            )
        )
        return V1Secret(metadata=result.manifest.metadata, data=result.manifest.data, type=result.manifest.get("type"))

    async def delete_secret(self, name: str) -> None:
        """Delete a secret."""
        return await self.cached_client.delete(
            K8sObjectMeta(
                name=name,
                namespace=self.namespace,
                cluster=self.cluster,
                kind=Secret.kind,
                version=Secret.version,
            )
        )

    async def patch_secret(self, name: str, patch: dict[str, Any] | list[dict[str, Any]]) -> None:
        """Patch a secret."""
        result = await self.cached_client.get_api_object(
            K8sObjectMeta(
                name=name,
                namespace=self.namespace,
                cluster=self.cluster,
                kind=Secret.kind,
                version=Secret.version,
            )
        )
        if result is None:
            raise errors.MissingResourceError(message=f"Cannot find secret {name}.")
        secret = result.obj
        assert isinstance(secret, Secret)

        patch_type: str | None = None  # rfc7386 patch
        if isinstance(patch, list):
            patch_type = "json"  # rfc6902 patch

        with suppress(NotFoundError):
            await secret.patch(patch, type=patch_type)
