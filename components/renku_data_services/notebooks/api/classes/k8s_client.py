"""An abstraction over the kr8s kubernetes client and the k8s-watcher."""

import base64
import json
import logging
from contextlib import suppress
from typing import Any, Generic, Optional, TypeVar, cast
from urllib.parse import urljoin

import httpx
from kr8s import NotFoundError, ServerError
from kr8s.asyncio.objects import APIObject, Pod, Secret, StatefulSet
from kubernetes.client import ApiClient, V1Container, V1Secret

from renku_data_services.errors import errors
from renku_data_services.notebooks.api.classes.auth import GitlabToken, RenkuTokens
from renku_data_services.notebooks.crs import AmaltheaSessionV1Alpha1, JupyterServerV1Alpha1
from renku_data_services.notebooks.errors.intermittent import (
    CannotStartServerError,
    DeleteServerError,
    IntermittentError,
    JSCacheError,
    PatchServerError,
)
from renku_data_services.notebooks.errors.programming import ProgrammingError
from renku_data_services.notebooks.errors.user import MissingResourceError
from renku_data_services.notebooks.util.kubernetes_ import find_env_var
from renku_data_services.notebooks.util.retries import (
    retry_with_exponential_backoff_async,
)

sanitize_for_serialization = ApiClient().sanitize_for_serialization


# NOTE The type ignore below is because the kr8s library has no type stubs, they claim pyright better handles type hints
class AmaltheaSessionV1Alpha1Kr8s(APIObject):  # type: ignore
    """Spec for amalthea sessions used by the k8s client."""

    kind: str = "AmaltheaSession"
    version: str = "amalthea.dev/v1alpha1"
    namespaced: bool = True
    plural: str = "amaltheasessions"
    singular: str = "amaltheasession"
    scalable: bool = False
    endpoint: str = "amaltheasessions"


# NOTE The type ignore below is because the kr8s library has no type stubs, they claim pyright better handles type hints
class JupyterServerV1Alpha1Kr8s(APIObject):  # type: ignore
    """Spec for jupyter servers used by the k8s client."""

    kind: str = "JupyterServer"
    version: str = "amalthea.dev/v1alpha1"
    namespaced: bool = True
    plural: str = "jupyterservers"
    singular: str = "jupyterserver"
    scalable: bool = False
    endpoint: str = "jupyterservers"


_SessionType = TypeVar("_SessionType", JupyterServerV1Alpha1, AmaltheaSessionV1Alpha1)
_Kr8sType = TypeVar("_Kr8sType", JupyterServerV1Alpha1Kr8s, AmaltheaSessionV1Alpha1Kr8s)


class NamespacedK8sClient(Generic[_SessionType, _Kr8sType]):
    """A kubernetes client that operates in a specific namespace."""

    def __init__(self, namespace: str, server_type: type[_SessionType], kr8s_type: type[_Kr8sType]):
        self.namespace = namespace
        self.server_type: type[_SessionType] = server_type
        self._kr8s_type: type[_Kr8sType] = kr8s_type
        if (self.server_type == AmaltheaSessionV1Alpha1 and self._kr8s_type == JupyterServerV1Alpha1Kr8s) or (
            self.server_type == JupyterServerV1Alpha1 and self._kr8s_type == AmaltheaSessionV1Alpha1Kr8s
        ):
            raise errors.ProgrammingError(message="Incompatible manifest and client types in k8s client")
        self.sanitize = ApiClient().sanitize_for_serialization

    async def get_pod_logs(self, name: str, max_log_lines: Optional[int] = None) -> dict[str, str]:
        """Get the logs of all containers in the session."""
        pod = cast(Pod, await Pod.get(name=name, namespace=self.namespace))
        logs: dict[str, str] = {}
        containers = [i.name for i in pod.spec.containers] + [i.name for i in pod.spec.initContainers]
        for container in containers:
            try:
                # NOTE: calling pod.logs without a container name set crashes the library
                clogs: list[str] = [i async for i in pod.logs(container=container, tail_lines=max_log_lines)]
            except NotFoundError:
                raise errors.MissingResourceError(message=f"The session pod {name} does not exist.")
            except ServerError as err:
                if err.status == 404:
                    raise errors.MissingResourceError(message=f"The session pod {name} does not exist.")
                raise
            else:
                logs[container] = "\n".join(clogs)
        return logs

    async def get_secret(self, name: str) -> Secret | None:
        """Read a specific secret from the cluster."""
        try:
            secret = await Secret.get(name, self.namespace)
        except NotFoundError:
            return None
        return secret

    async def create_server(self, manifest: _SessionType) -> _SessionType:
        """Create a jupyter server in the cluster."""
        # NOTE: You have to exclude none when using model dump below because otherwise we get
        # namespace=null which seems to break the kr8s client or simply k8s does not translate
        # namespace = null to the default namespace.
        manifest.metadata.namespace = self.namespace
        js = await self._kr8s_type(manifest.model_dump(exclude_none=True, mode="json"))
        server_name = manifest.metadata.name
        try:
            await js.create()
        except ServerError as e:
            logging.exception(f"Cannot start server {server_name} because of {e}")
            raise CannotStartServerError(
                message=f"Cannot start the session {server_name}",
            )
        # NOTE: If refresh is not called then upon creating the object the status is blank
        await js.refresh()
        # NOTE: We wait for the cache to sync with the newly created server
        # If not then the user will get a non-null response from the POST request but
        # then immediately after a null response because the newly created server has
        # not made it into the cache. With this we wait for the cache to catch up
        # before we send the response from the POST request out. Exponential backoff
        # is used to avoid overwhelming the cache.
        server = await retry_with_exponential_backoff_async(lambda x: x is None)(self.get_server)(server_name)
        if server is None:
            raise CannotStartServerError(message=f"Cannot start the session {server_name}")
        return server

    async def patch_server(self, server_name: str, patch: dict[str, Any] | list[dict[str, Any]]) -> _SessionType:
        """Patch the server."""
        server = await self._kr8s_type(dict(metadata=dict(name=server_name, namespace=self.namespace)))
        patch_type: str | None = None  # rfc7386 patch
        if isinstance(patch, list):
            patch_type = "json"  # rfc6902 patch
        try:
            await server.patch(patch, type=patch_type)
        except ServerError as e:
            logging.exception(f"Cannot patch server {server_name} because of {e}")
            raise PatchServerError()

        return self.server_type.model_validate(server.to_dict())

    async def patch_statefulset(
        self, server_name: str, patch: dict[str, Any] | list[dict[str, Any]]
    ) -> StatefulSet | None:
        """Patch a statefulset."""
        sts = await StatefulSet(dict(metadata=dict(name=server_name, namespace=self.namespace)))
        patch_type: str | None = None  # rfc7386 patch
        if isinstance(patch, list):
            patch_type = "json"  # rfc6902 patch
        try:
            await sts.patch(patch, type=patch_type)
        except ServerError as err:
            if err.status == 404:
                # NOTE: It can happen potentially that another request or something else
                # deleted the session as this request was going on, in this case we ignore
                # the missing statefulset
                return None
            raise
        return sts

    async def delete_server(self, server_name: str) -> None:
        """Delete the server."""
        server = await self._kr8s_type(dict(metadata=dict(name=server_name, namespace=self.namespace)))
        try:
            await server.delete(propagation_policy="Foreground")
        except ServerError as e:
            logging.exception(f"Cannot delete server {server_name} because of {e}")
            raise DeleteServerError()
        return None

    async def get_server(self, name: str) -> _SessionType | None:
        """Get a specific JupyterServer object."""
        try:
            server = await self._kr8s_type.get(name=name, namespace=self.namespace)
        except NotFoundError:
            return None
        except ServerError as err:
            if err.status not in [400, 404]:
                logging.exception(f"Cannot get server {name} because of {err}")
                raise IntermittentError(f"Cannot get server {name} from the k8s API.")
            return None
        return self.server_type.model_validate(server.to_dict())

    async def list_servers(self, label_selector: Optional[str] = None) -> list[_SessionType]:
        """Get a list of k8s jupyterserver objects for a specific user."""
        try:
            servers = await self._kr8s_type.list(namespace=self.namespace, label_selector=label_selector)
        except ServerError as err:
            if err.status not in [400, 404]:
                logging.exception(f"Cannot list servers because of {err}")
                raise IntermittentError(f"Cannot list servers from the k8s API with selector {label_selector}.")
            return []
        output: list[_SessionType] = (
            [self.server_type.model_validate(servers.to_dict())]
            if isinstance(servers, APIObject)
            else [self.server_type.model_validate(server.to_dict()) for server in servers]
        )
        return output

    async def patch_image_pull_secret(self, server_name: str, gitlab_token: GitlabToken) -> None:
        """Patch the image pull secret used in a Renku session."""
        secret_name = f"{server_name}-image-secret"
        try:
            secret = cast(Secret, await Secret.get(name=secret_name, namespace=self.namespace))
        except NotFoundError:
            return None
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

    async def patch_statefulset_tokens(self, name: str, renku_tokens: RenkuTokens) -> None:
        """Patch the Renku and Gitlab access tokens that are used in the session statefulset."""
        try:
            sts = cast(StatefulSet, await StatefulSet.get(name=name, namespace=self.namespace))
        except NotFoundError:
            return None

        containers: list[V1Container] = [V1Container(**i) for i in sts.spec.template.spec.containers]
        init_containers: list[V1Container] = [V1Container(**i) for i in sts.spec.template.spec.init_containers]

        git_proxy_container_index, git_proxy_container = next(
            ((i, c) for i, c in enumerate(containers) if c.name == "git-proxy"),
            (None, None),
        )
        git_clone_container_index, git_clone_container = next(
            ((i, c) for i, c in enumerate(init_containers) if c.name == "git-proxy"),
            (None, None),
        )
        secrets_container_index, secrets_container = next(
            ((i, c) for i, c in enumerate(init_containers) if c.name == "init-user-secrets"),
            (None, None),
        )

        git_proxy_renku_access_token_env = (
            find_env_var(git_proxy_container, "GIT_PROXY_RENKU_ACCESS_TOKEN")
            if git_proxy_container is not None
            else None
        )
        git_proxy_renku_refresh_token_env = (
            find_env_var(git_proxy_container, "GIT_PROXY_RENKU_REFRESH_TOKEN")
            if git_proxy_container is not None
            else None
        )
        git_clone_renku_access_token_env = (
            find_env_var(git_clone_container, "GIT_CLONE_USER__RENKU_TOKEN")
            if git_clone_container is not None
            else None
        )
        secrets_renku_access_token_env = (
            find_env_var(secrets_container, "RENKU_ACCESS_TOKEN") if secrets_container is not None else None
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
                        f"/spec/template/spec/containers/{git_clone_container_index}"
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
                        f"/spec/template/spec/containers/{secrets_container_index}"
                        f"/env/{secrets_renku_access_token_env[0]}/value"
                    ),
                    "value": renku_tokens.access_token,
                },
            )

        if not patches:
            return None

        await sts.patch(patches, type="json")

    async def create_secret(self, secret: V1Secret) -> V1Secret:
        """Create a new secret."""

        new_secret = await Secret(self.sanitize(secret), self.namespace)
        await new_secret.create()
        return V1Secret(metadata=new_secret.metadata, data=new_secret.data, type=new_secret.raw.get("type"))

    async def delete_secret(self, name: str) -> None:
        """Delete a secret."""
        secret = await Secret(dict(metadata=dict(name=name, namespace=self.namespace)))
        with suppress(NotFoundError):
            await secret.delete()
        return None


class ServerCache(Generic[_SessionType]):
    """Utility class for calling the jupyter server cache."""

    def __init__(self, url: str, server_type: type[_SessionType]):
        self.url = url
        self.client = httpx.AsyncClient()
        self.server_type: type[_SessionType] = server_type

    async def list_servers(self, safe_username: str) -> list[_SessionType]:
        """List the jupyter servers."""
        url = urljoin(self.url, f"/users/{safe_username}/servers")
        try:
            res = await self.client.get(url, timeout=10)
        except httpx.RequestError as err:
            logging.warning(f"Jupyter server cache at {url} cannot be reached: {err}")
            raise JSCacheError("The jupyter server cache is not available")
        if res.status_code != 200:
            logging.warning(
                f"Listing servers at {url} from "
                f"jupyter server cache failed with status code: {res.status_code} "
                f"and body: {res.text}"
            )
            raise JSCacheError(f"The JSCache produced an unexpected status code: {res.status_code}")

        return [self.server_type.model_validate(i) for i in res.json()]

    async def get_server(self, name: str) -> _SessionType | None:
        """Get a specific jupyter server."""
        url = urljoin(self.url, f"/servers/{name}")
        try:
            res = await self.client.get(url, timeout=10)
        except httpx.RequestError as err:
            logging.warning(f"Jupyter server cache at {url} cannot be reached: {err}")
            raise JSCacheError("The jupyter server cache is not available")
        if res.status_code != 200:
            logging.warning(
                f"Reading server at {url} from "
                f"jupyter server cache failed with status code: {res.status_code} "
                f"and body: {res.text}"
            )
            raise JSCacheError(f"The JSCache produced an unexpected status code: {res.status_code}")
        output = res.json()
        if len(output) == 0:
            return None
        if len(output) > 1:
            raise ProgrammingError(f"Expected to find 1 server when getting server {name}, " f"found {len(output)}.")
        return self.server_type.model_validate(output[0])


class K8sClient(Generic[_SessionType, _Kr8sType]):
    """The K8s client that combines a namespaced client and a jupyter server cache."""

    def __init__(
        self,
        cache: ServerCache[_SessionType],
        renku_ns_client: NamespacedK8sClient[_SessionType, _Kr8sType],
        username_label: str,
    ):
        self.cache: ServerCache[_SessionType] = cache
        self.renku_ns_client: NamespacedK8sClient[_SessionType, _Kr8sType] = renku_ns_client
        self.username_label = username_label
        if not self.username_label:
            raise ProgrammingError("username_label has to be provided to K8sClient")
        self.sanitize = self.renku_ns_client.sanitize

    async def list_servers(self, safe_username: str) -> list[_SessionType]:
        """Get a list of servers that belong to a user.

        Attempt to use the cache first but if the cache fails then use the k8s API.
        """
        try:
            return await self.cache.list_servers(safe_username)
        except JSCacheError:
            logging.warning(f"Skipping the cache to list servers for user: {safe_username}")
            label_selector = f"{self.username_label}={safe_username}"
            return await self.renku_ns_client.list_servers(label_selector)

    async def get_server(self, name: str, safe_username: str) -> _SessionType | None:
        """Attempt to get a specific server by name from the cache.

        If the request to the cache fails, fallback to the k8s API.
        """
        server = None
        try:
            server = await self.cache.get_server(name)
        except JSCacheError:
            server = await self.renku_ns_client.get_server(name)

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
            raise MissingResourceError(
                f"Cannot find server {server_name} for user " f"{safe_username} to retrieve logs."
            )
        pod_name = f"{server_name}-0"
        return await self.renku_ns_client.get_pod_logs(pod_name, max_log_lines)

    async def _get_secret(self, name: str) -> Secret | None:
        """Get a specific secret."""
        return await self.renku_ns_client.get_secret(name)

    async def create_server(self, manifest: _SessionType, safe_username: str) -> _SessionType:
        """Create a server."""
        server_name = manifest.metadata.name
        server = await self.get_server(server_name, safe_username)
        if server:
            # NOTE: server already exists
            return server
        manifest.metadata.labels[self.username_label] = safe_username
        return await self.renku_ns_client.create_server(manifest)

    async def patch_server(
        self, server_name: str, safe_username: str, patch: dict[str, Any] | list[dict[str, Any]]
    ) -> _SessionType:
        """Patch a server."""
        server = await self.get_server(server_name, safe_username)
        if not server:
            raise MissingResourceError(
                f"Cannot find server {server_name} for user " f"{safe_username} in order to patch it."
            )
        return await self.renku_ns_client.patch_server(server_name=server_name, patch=patch)

    async def patch_statefulset(
        self, server_name: str, patch: dict[str, Any] | list[dict[str, Any]]
    ) -> StatefulSet | None:
        """Patch a statefulset."""
        client = self.renku_ns_client
        return await client.patch_statefulset(server_name=server_name, patch=patch)

    async def delete_server(self, server_name: str, safe_username: str) -> None:
        """Delete the server."""
        server = await self.get_server(server_name, safe_username)
        if not server:
            return None
        await self.renku_ns_client.delete_server(server_name)
        return None

    async def patch_tokens(self, server_name: str, renku_tokens: RenkuTokens, gitlab_token: GitlabToken) -> None:
        """Patch the Renku and Gitlab access tokens used in a session."""
        client = self.renku_ns_client
        await client.patch_statefulset_tokens(server_name, renku_tokens)
        await client.patch_image_pull_secret(server_name, gitlab_token)

    @property
    def preferred_namespace(self) -> str:
        """Get the preferred namespace for creating jupyter servers."""
        return self.renku_ns_client.namespace

    async def create_secret(self, secret: V1Secret) -> V1Secret:
        """Create a secret."""
        return await self.renku_ns_client.create_secret(secret)

    async def delete_secret(self, name: str) -> None:
        """Delete a secret."""
        return await self.renku_ns_client.delete_secret(name)
