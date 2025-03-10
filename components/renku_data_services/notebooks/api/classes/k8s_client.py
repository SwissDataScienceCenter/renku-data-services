"""An abstraction over the kr8s kubernetes client and the k8s-watcher."""

import asyncio
import base64
import glob
import json
import logging
import os
from abc import ABC, abstractmethod
from contextlib import suppress
from typing import Any, Final, Generic, Optional, TypeVar, cast
from urllib.parse import urljoin

import httpx
import kr8s
import kubernetes
from box.box import Box
from expiringdict import ExpiringDict
from kr8s import NotFoundError, ServerError
from kr8s.asyncio.objects import APIObject, Pod, Secret, StatefulSet
from kubernetes.client import V1Secret

from renku_data_services.base_models import AnonymousAPIUser, APIUser, AuthenticatedAPIUser
from renku_data_services.crc.db import ResourcePoolRepository
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
from renku_data_services.notebooks.util.kubernetes_ import find_env_var
from renku_data_services.notebooks.util.retries import (
    retry_with_exponential_backoff_async,
)


# NOTE The type ignore below is because the kr8s library has no type stubs, they claim pyright better handles type hints
class AmaltheaSessionV1Alpha1Kr8s(APIObject):
    """Spec for amalthea sessions used by the k8s client."""

    kind: str = "AmaltheaSession"
    version: str = "amalthea.dev/v1alpha1"
    namespaced: bool = True
    plural: str = "amaltheasessions"
    singular: str = "amaltheasession"
    scalable: bool = False
    endpoint: str = "amaltheasessions"


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
_Kr8sType = TypeVar("_Kr8sType", JupyterServerV1Alpha1Kr8s, AmaltheaSessionV1Alpha1Kr8s)

_sanitizer = kubernetes.client.ApiClient().sanitize_for_serialization

DEFAULT_K8S_CLUSTER: Final[str] = "default_k8s_cluster"


class K8sClientProto[_SessionType, _Kr8sType](ABC):
    """K8s Client wrapper interface."""

    @abstractmethod
    def sanitize(self, obj: APIObject) -> Any:
        """Sanitize a JSON object."""
        raise NotImplementedError()

    @abstractmethod
    def namespace(self) -> str:
        """Return the current kubernetes namespace."""
        raise NotImplementedError()

    @abstractmethod
    async def cluster_name_by_class_id(self, class_id: int | None, api_user: APIUser) -> str:
        """Retrieve the cluster name given the resource class id."""
        raise NotImplementedError()

    @abstractmethod
    async def list_servers(self, safe_username: str) -> list[_SessionType]:
        """List all the user sessions visible from the safe_username."""
        raise NotImplementedError()

    @abstractmethod
    async def create_server(
        self, manifest: _SessionType, api_user: AnonymousAPIUser | AuthenticatedAPIUser
    ) -> _SessionType:
        """Launch a user session."""
        raise NotImplementedError()

    @abstractmethod
    async def get_server(self, name: str, safe_username: str) -> _SessionType | None:
        """Lookup a user session by name."""
        raise NotImplementedError()

    @abstractmethod
    async def get_server_logs(
        self, server_name: str, safe_username: str, max_log_lines: Optional[int] = None
    ) -> dict[str, str]:
        """Retrieve the logs for the given user session."""
        raise NotImplementedError()

    @abstractmethod
    async def patch_server(
        self, server_name: str, safe_username: str, patch: dict[str, Any] | list[dict[str, Any]]
    ) -> _SessionType:
        """Patch the user session."""
        raise NotImplementedError()

    @abstractmethod
    async def delete_server(self, server_name: str, safe_username: str) -> None:
        """Delete the provided user session."""
        raise NotImplementedError()

    @abstractmethod
    async def patch_server_tokens(self, server_name: str, renku_tokens: RenkuTokens, gitlab_token: GitlabToken) -> None:
        """Patch user authentication tokens in a user session."""
        raise NotImplementedError()

    @abstractmethod
    async def patch_statefulset(
        self, server_name: str, patch: dict[str, Any] | list[dict[str, Any]]
    ) -> StatefulSet | None:
        """Patch a user session."""
        raise NotImplementedError()

    @abstractmethod
    async def create_secret(self, secret: V1Secret) -> V1Secret:
        """Create a kubernetes secret."""
        raise NotImplementedError()

    @abstractmethod
    async def delete_secret(self, name: str) -> None:
        """Delete a kubernetes secret."""
        raise NotImplementedError()


# WARNING:
#   As of mypy 1.14.1, it does not support instantiating an object using a field containing a type using the new syntax,
#    which is why we have a mix of new and old syntax for the generics.


class _BaseK8sClient(Generic[_SessionType, _Kr8sType]):
    """A kubernetes client that operates in a specific namespace."""

    # Mypy does not support inferring type dynamically from another generic type (_SessionType => _Kr8sType)
    def __init__(
        self, server_type: type[_SessionType], kr8s_type: type[_Kr8sType], api: kr8s.asyncio.Api, username_label: str
    ):
        self._api = api
        self._server_type: type[_SessionType] = server_type
        self._kr8s_type: type[_Kr8sType] = kr8s_type
        if (self._server_type == AmaltheaSessionV1Alpha1 and self._kr8s_type == JupyterServerV1Alpha1Kr8s) or (
            self._server_type == JupyterServerV1Alpha1 and self._kr8s_type == AmaltheaSessionV1Alpha1Kr8s
        ):
            raise errors.ProgrammingError(message="Incompatible manifest and client types in k8s client")

        self._username_label = username_label

    @property
    def namespace(self) -> str:
        return self._api.namespace

    async def get_pod_logs(self, name: str, max_log_lines: int | None = None) -> dict[str, str]:
        """Get the logs of all containers in the session."""
        pod = await Pod.get(api=self._api, name=name)
        logs: dict[str, str] = {}
        containers = [container.name for container in pod.spec.containers + pod.spec.get("initContainers", [])]
        for container in containers:
            try:
                # NOTE: calling pod.logs without a container name set crashes the library
                clogs: list[str] = [clog async for clog in pod.logs(container=container, tail_lines=max_log_lines)]
            except httpx.ResponseNotRead:
                # NOTE: This occurs when the container is still starting, but we try to read its logs
                continue
            except NotFoundError:
                raise errors.MissingResourceError(message=f"The session pod {name} does not exist.")
            except ServerError as err:
                if err.status == "404":
                    raise errors.MissingResourceError(message=f"The session pod {name} does not exist.")
                raise
            else:
                logs[container] = "\n".join(clogs)
        return logs

    async def get_secret(self, name: str) -> Secret | None:
        """Read a specific secret from the cluster."""
        try:
            secret = await Secret.get(api=self._api, name=name)
        except NotFoundError:
            return None
        return secret

    async def create_server(self, manifest: _SessionType) -> _SessionType:
        """Create a jupyter server in the cluster."""

        # NOTE: You have to exclude none when using model dump below because otherwise we get
        # namespace=null which seems to break the kr8s client or simply k8s does not translate
        # namespace = null to the default namespace.
        js = await self._kr8s_type(
            api=self._api, namespace=self.namespace, resource=manifest.model_dump(exclude_none=True, mode="json")
        )
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
        server = await self._kr8s_type(
            api=self._api, namespace=self.namespace, resource=dict(metadata=dict(name=server_name))
        )
        patch_type: str | None = None  # rfc7386 patch
        if isinstance(patch, list):
            patch_type = "json"  # rfc6902 patch
        try:
            await server.patch(patch, type=patch_type)
        except ServerError as e:
            logging.exception(f"Cannot patch server {server_name} because of {e}")
            raise PatchServerError()

        return self._server_type.model_validate(server.to_dict())

    async def patch_statefulset(
        self, server_name: str, patch: dict[str, Any] | list[dict[str, Any]]
    ) -> StatefulSet | None:
        """Patch a statefulset."""
        sts = await StatefulSet(api=self._api, namespace=self.namespace, resource=dict(metadata=dict(name=server_name)))
        patch_type: str | None = None  # rfc7386 patch
        if isinstance(patch, list):
            patch_type = "json"  # rfc6902 patch
        try:
            await sts.patch(patch, type=patch_type)
        except ServerError as err:
            if err.response is not None and err.response.status_code == 404:
                # NOTE: It can happen potentially that another request or something else
                # deleted the session as this request was going on, in this case we ignore
                # the missing statefulset
                return None
            raise
        return cast(StatefulSet, sts)

    async def delete_server(self, server_name: str) -> None:
        """Delete the server."""
        server = await self._kr8s_type(
            api=self._api, namespace=self.namespace, resource=dict(metadata=dict(name=server_name))
        )
        try:
            await server.delete(propagation_policy="Foreground")
        except ServerError as e:
            logging.exception(f"Cannot delete server {server_name} because of {e}")
            raise DeleteServerError()
        return None

    async def get_server(self, name: str, num_retries: int = 0) -> _SessionType | None:
        """Get a specific JupyterServer object."""
        try:
            server = await self._kr8s_type.get(api=self._api, name=name)
        except NotFoundError:
            return None
        except ServerError as err:
            if err.response is not None and err.response.status_code == 429:
                retry_after_sec = err.response.headers.get("Retry-After")
                logging.warning(
                    "Received 429 status code from k8s when getting server "
                    f"will wait for {retry_after_sec} seconds and retry"
                )
                if isinstance(retry_after_sec, str) and retry_after_sec.isnumeric() and num_retries < 3:
                    await asyncio.sleep(int(retry_after_sec))
                    return await self.get_server(name, num_retries=num_retries + 1)
            if err.response is None or err.response.status_code not in [400, 404]:
                logging.exception(f"Cannot get server {name} because of {err}")
                raise IntermittentError(f"Cannot get server {name} from the k8s API.")
            return None
        return self._server_type.model_validate(server.to_dict())

    async def list_servers(self, safe_username: str) -> list[_SessionType]:
        """Get a list of k8s jupyterserver objects for a specific user."""

        label_selector = f"{self._username_label}={safe_username}"
        try:
            # We cannot use kr8s.APIObject.list as it ignores the api object argument and instead instantiate a default
            # one, so let's do this by hand (Mostly a copy-pasta of the aforementioned function, adapted to use the
            # correct api object).
            resources = await self._api.async_get(kind=self._kr8s_type, api=self._api, label_selector=label_selector)
            if not isinstance(resources, list):
                resources = [resources]
            servers = [resource for resource in resources if isinstance(resource, self._kr8s_type)]

        except ServerError as err:
            if err.response is None or err.response.status_code not in [400, 404]:
                logging.exception(f"Cannot list servers because of {err}")
                raise IntermittentError(f"Cannot list servers from the k8s API with selector {label_selector}.")
            return []
        output: list[_SessionType] = [self._server_type.model_validate(server.to_dict()) for server in servers]
        return output

    async def patch_image_pull_secret(self, server_name: str, gitlab_token: GitlabToken) -> None:
        """Patch the image pull secret used in a Renku session."""
        secret_name = f"{server_name}-image-secret"
        secret = await self.get_secret(secret_name)
        if secret is None:
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
        await secret.patch(patch=patch, type="json")

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

    async def patch_statefulset_tokens(self, name: str, renku_tokens: RenkuTokens) -> None:
        """Patch the Renku and Gitlab access tokens that are used in the session statefulset."""
        if self._server_type != JupyterServerV1Alpha1 or self._kr8s_type != JupyterServerV1Alpha1Kr8s:
            raise NotImplementedError("patch_statefulset_tokens is only implemented for JupyterServers")
        try:
            sts = await StatefulSet.get(api=self._api, name=name)
        except NotFoundError:
            return None

        patches = self._get_statefulset_token_patches(sts, renku_tokens)
        if not patches:
            return
        await sts.patch(patches, type="json")

    async def create_secret(self, secret: V1Secret) -> V1Secret:
        """Create a new secret."""

        new_secret = await Secret(api=self._api, namespace=self.namespace, resource=_sanitizer(secret))
        await new_secret.create()
        return V1Secret(metadata=new_secret.metadata, data=new_secret.data, type=new_secret.raw.get("type"))

    async def delete_secret(self, name: str) -> None:
        """Delete a secret."""
        secret = await self.get_secret(name)
        if secret is not None:
            with suppress(NotFoundError):
                await secret.delete()
        return None

    async def patch_secret(self, name: str, patch: dict[str, Any] | list[dict[str, Any]]) -> None:
        """Patch a secret."""
        patch_type: str | None = None  # rfc7386 patch
        if isinstance(patch, list):
            patch_type = "json"  # rfc6902 patch
        secret = await self.get_secret(name)
        if secret is None:
            raise errors.MissingResourceError(message=f"Cannot find secret {name}.")
        with suppress(NotFoundError):
            await secret.patch(patch, type=patch_type)


class _ServerCache(Generic[_SessionType]):
    """Utility class for calling the jupyter server cache."""

    def __init__(self, url: str, server_type: type[_SessionType]):
        self.url = url
        self.client = httpx.AsyncClient(timeout=10)
        self.server_type: type[_SessionType] = server_type
        self.url_path_name = "servers"
        if server_type == AmaltheaSessionV1Alpha1:
            self.url_path_name = "sessions"

    async def list_servers(self, safe_username: str) -> list[_SessionType]:
        """List the jupyter servers."""
        url = urljoin(self.url, f"/users/{safe_username}/{self.url_path_name}")
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

        return [self.server_type.model_validate(server) for server in res.json()]

    async def get_server(self, name: str) -> _SessionType | None:
        """Get a specific jupyter server."""
        url = urljoin(self.url, f"/{self.url_path_name}/{name}")
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
            raise ProgrammingError(f"Expected to find 1 server when getting server {name}, found {len(output)}.")
        return self.server_type.model_validate(output[0])


class _CachedK8sClient[_SessionType, _Kr8sType](_BaseK8sClient):
    """Cached K8s client. NB: Not everything is cached at the moment."""

    def __init__(
        self,
        server_type: type[_SessionType],
        kr8s_type: type[_Kr8sType],
        api: kr8s.asyncio.Api,
        cache_url: str,
        username_label: str,
        # NOTE: If cache skipping is enabled then when the cache fails a large number of
        # sessions can overload the k8s API by submitting a lot of calls directly.
        skip_cache_if_unavailable: bool = False,
    ):
        super().__init__(server_type, kr8s_type, api, username_label)
        self._cache: _ServerCache = _ServerCache(cache_url, server_type)
        self._username_label = username_label
        self._skip_cache_if_unavailable = skip_cache_if_unavailable

    async def list_servers(self, safe_username: str) -> list[_SessionType]:
        """Get a list of servers that belong to a user.

        Attempt to use the cache first but if the cache fails then use the k8s API.
        """
        try:
            return await self._cache.list_servers(safe_username)
        except JSCacheError:
            if self._skip_cache_if_unavailable:
                logging.warning(f"Skipping the cache to list servers for user: {safe_username}")
                return await super().list_servers(safe_username)
            else:
                raise

    async def get_server(self, name: str, num_retries: int = 0) -> _SessionType | None:
        """Get a list a server.

        Attempt to use the cache first but if the cache fails then use the k8s API.
        """
        try:
            return await self._cache.get_server(name)
        except JSCacheError:
            if self._skip_cache_if_unavailable:
                return await super().get_server(name, num_retries)
            else:
                raise


class _SingleK8sClient(Generic[_SessionType, _Kr8sType]):
    """The K8s client that combines a namespaced client and a jupyter server cache."""

    def __init__(
        self,
        server_type: type[_SessionType],
        kr8s_type: type[_Kr8sType],
        api: kr8s.asyncio.Api,
        cache_url: str,
        username_label: str,
        skip_cache_if_unavailable: bool = False,
    ):
        self._k8s_client: _BaseK8sClient[_SessionType, _Kr8sType] = _CachedK8sClient(
            server_type, kr8s_type, api, cache_url, username_label, skip_cache_if_unavailable
        )

        self.username_label = username_label
        if not self.username_label:
            raise ProgrammingError("username_label has to be provided to K8sClient")

    async def list_servers(self, safe_username: str) -> list[_SessionType]:
        """Get a list of servers that belong to a user."""
        return await self._k8s_client.list_servers(safe_username=safe_username)

    async def get_server(self, name: str, safe_username: str) -> _SessionType | None:
        """Attempt to get a specific server by name from the cache.

        If the request to the cache fails, fallback to the k8s API.
        """
        server: _SessionType | None = await self._k8s_client.get_server(name)

        # NOTE: only the user that the server belongs to can read it, without the line
        # below anyone can request and read any one else's server
        if (
            server is not None
            and server.metadata is not None
            and server.metadata.labels.get(self.username_label) != safe_username
        ):
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
        return await self._k8s_client.get_pod_logs(pod_name, max_log_lines)

    async def create_server(self, manifest: _SessionType, safe_username: str) -> _SessionType:
        """Create a server."""
        server_name = manifest.metadata.name
        server = await self.get_server(server_name, safe_username)
        if server:
            # NOTE: server already exists
            return server
        manifest.metadata.labels[self.username_label] = safe_username
        return await self._k8s_client.create_server(manifest)

    async def patch_server(
        self, server_name: str, safe_username: str, patch: dict[str, Any] | list[dict[str, Any]]
    ) -> _SessionType:
        """Patch a server."""
        server = await self.get_server(server_name, safe_username)
        if not server:
            raise errors.MissingResourceError(
                message=f"Cannot find server {server_name} for user {safe_username} in order to patch it."
            )
        return await self._k8s_client.patch_server(server_name=server_name, patch=patch)

    async def delete_server(self, server_name: str, safe_username: str) -> None:
        """Delete the server."""
        server = await self.get_server(server_name, safe_username)
        if not server:
            raise errors.MissingResourceError(
                message=f"Cannot find server {server_name} for user {safe_username} in order to delete it."
            )
        return await self._k8s_client.delete_server(server_name)

    async def patch_server_tokens(self, server_name: str, renku_tokens: RenkuTokens, gitlab_token: GitlabToken) -> None:
        """Patch the Renku and Gitlab access tokens used in a session."""
        await self._k8s_client.patch_statefulset_tokens(server_name, renku_tokens)
        await self._k8s_client.patch_image_pull_secret(server_name, gitlab_token)

    @property
    def namespace(self) -> str:
        """Get the preferred namespace for creating jupyter servers."""
        return self._k8s_client.namespace

    async def patch_statefulset(
        self, server_name: str, patch: dict[str, Any] | list[dict[str, Any]]
    ) -> StatefulSet | None:
        return await self._k8s_client.patch_statefulset(server_name, patch)

    async def create_secret(self, secret: V1Secret) -> V1Secret:
        return await self._k8s_client.create_secret(secret)

    async def delete_secret(self, name: str) -> None:
        await self._k8s_client.delete_secret(name)


class MultipleK8sClient(K8sClientProto[_SessionType, _Kr8sType]):
    """Multiple Kubernetes cluster client wrapper."""

    def __init__(
        self,
        server_type: type[_SessionType],
        kr8s_type: type[_Kr8sType],
        cache_url: str,
        username_label: str,
        rp_repo: ResourcePoolRepository,
        skip_cache_if_unavailable: bool = False,
    ):
        self._clients: dict[str, _SingleK8sClient[_SessionType, _Kr8sType]] = dict()
        self._kube_conf_root_dir = "/secrets/kube_configs"
        self._rp_repo = rp_repo

        # Add at least one connection, to the default cluster.
        self._clients[DEFAULT_K8S_CLUSTER] = _SingleK8sClient(
            server_type,
            kr8s_type,
            kr8s.api(),
            cache_url,
            username_label,
            skip_cache_if_unavailable,
        )

        if os.path.exists(self._kube_conf_root_dir):
            for filename in glob.glob(pathname="*.yaml", root_dir=self.kube_conf_root_dir):
                self._clients[filename.removesuffix(".yaml")] = _SingleK8sClient(
                    server_type,
                    kr8s_type,
                    kr8s.api(kubeconfig=f"{self.kube_conf_root_dir}/{filename}"),
                    cache_url,
                    username_label,
                    skip_cache_if_unavailable,
                )
        else:
            logging.warning(f"Cannot open directory '{self._kube_conf_root_dir}', ignoring kube configs...")

        # maps session/server name to k8s client
        self._session2client: ExpiringDict[str, _SingleK8sClient[_SessionType, _Kr8sType]] = ExpiringDict(
            max_len=10_000, max_age_seconds=1 * 24 * 3600
        )

    async def _client_by_session(
        self, session_name: str, safe_username: str
    ) -> _SingleK8sClient[_SessionType, _Kr8sType] | None:
        # Try in our cache, if not there look it up in K8s and update our cache
        client: _SingleK8sClient[_SessionType, _Kr8sType] | None = self._session2client.get(session_name, None)
        if client is None:
            for c in self._clients.values():
                if session_name in await c.list_servers(safe_username):
                    self._session2client[session_name] = c
                    client = c
                    break

        return client

    async def _client_by_class_id(self, class_id: str, api_user: APIUser) -> _SingleK8sClient[_SessionType, _Kr8sType]:
        # **NOTE**: This assumes class_ids are unique over all the clusters.
        _id = int(class_id)
        name = await self.cluster_name_by_class_id(_id, api_user)
        return self._clients[name]

    @property
    def kube_conf_root_dir(self) -> str:
        """Root folder of the kube configs."""
        return self._kube_conf_root_dir

    def sanitize(self, obj: APIObject) -> Any:
        """Sanitize json object."""
        return _sanitizer(obj)

    def namespace(self) -> str:
        """Current namespace of the main cluster."""
        # TODO: LSA Does not break current code, but bad, as it may be different based on the cluster
        return self._clients[DEFAULT_K8S_CLUSTER].namespace

    async def cluster_name_by_class_id(self, class_id: int | None, api_user: APIUser) -> str:
        """Retrieve the cluster name given the resource class id."""
        # If the config_name is not set or not found, fall back on the default cluster.
        name = DEFAULT_K8S_CLUSTER

        if class_id is not None:
            rp = await self._rp_repo.get_resource_pool_from_class(api_user, class_id)
            if rp.cluster is not None:
                name = rp.cluster.config_name

        return name

    async def list_servers(self, safe_username: str) -> list[_SessionType]:
        """List all the user sessions visible from the safe_username."""
        # Don't blame me, blame python's list comprehension syntax
        return [s for c in self._clients.values() for s in await c.list_servers(safe_username)]

    async def create_server(
        self, manifest: _SessionType, api_user: AnonymousAPIUser | AuthenticatedAPIUser
    ) -> _SessionType:
        """Launch a user session."""
        class_id = manifest.metadata.annotations["renku.io/resource_class_id"]
        server_name = manifest.metadata.name

        client = await self._client_by_class_id(class_id, api_user)

        session = await client.create_server(manifest, api_user.id)
        self._session2client[server_name] = client

        return session

    async def get_server(self, name: str, safe_username: str) -> _SessionType | None:
        """Lookup a user session by name."""
        client = await self._client_by_session(name, safe_username)
        if client is not None:
            return await client.get_server(name, safe_username)

        return None

    async def get_server_logs(
        self, server_name: str, safe_username: str, max_log_lines: Optional[int] = None
    ) -> dict[str, str]:
        """Retrieve the logs for the given user session."""
        client = await self._client_by_session(server_name, safe_username)
        if client is not None:
            return await client.get_server_logs(server_name, safe_username, max_log_lines)

        raise errors.MissingResourceError(
            message=f"Cannot find server {server_name} for user {safe_username} to retrieve logs."
        )

    async def patch_server(
        self, server_name: str, safe_username: str, patch: dict[str, Any] | list[dict[str, Any]]
    ) -> _SessionType:
        """Patch the user session."""
        client = await self._client_by_session(server_name, safe_username)
        if client is not None:
            return await client.patch_server(server_name, safe_username, patch)

        raise errors.MissingResourceError(
            message=f"Cannot find cluster connection to server {server_name}"
            f" for user {safe_username} in order to patch it."
        )

    async def delete_server(self, server_name: str, safe_username: str) -> None:
        """Delete the provided user session."""
        # Retrieve and remove from the mapping to the k8s client for this session
        client = self._session2client.pop(server_name, None)
        if client is not None:
            await client.delete_server(server_name, safe_username)

    async def patch_server_tokens(self, server_name: str, renku_tokens: RenkuTokens, gitlab_token: GitlabToken) -> None:
        """Patch user authentication tokens in a user session."""
        # TODO: Brute force this for now, not pretty
        for c in self._clients.values():
            await c.patch_server_tokens(server_name, renku_tokens, gitlab_token)

    async def patch_statefulset(
        self, server_name: str, patch: dict[str, Any] | list[dict[str, Any]]
    ) -> StatefulSet | None:
        """Patch a user session."""
        # TODO: Brute force this for now, not pretty
        for c in self._clients.values():
            r = await c.patch_statefulset(server_name, patch)
            if r is not None:
                return r

        # If the stateful set is missing, we ignore the operation
        return None

    async def create_secret(self, secret: V1Secret) -> V1Secret:
        """Create a kubernetes secret."""
        # TODO: LSA Does not break current code, but bad, as it may be different based on the cluster
        return await self._clients[DEFAULT_K8S_CLUSTER].create_secret(secret)

    async def delete_secret(self, name: str) -> None:
        """Delete a kubernetes secret."""
        # TODO: LSA Does not break current code, but bad, as it may be different based on the cluster
        await self._clients[DEFAULT_K8S_CLUSTER].delete_secret(name)


class DummyK8sClient(K8sClientProto[_SessionType, _Kr8sType]):
    """Dummy Kubernetes client wrapper for unit tests."""

    def sanitize(self, obj: APIObject) -> Any:
        """Sanitize a JSON object."""
        raise NotImplementedError()

    def namespace(self) -> str:
        """Return the current kubernetes namespace."""
        raise NotImplementedError()

    async def cluster_name_by_class_id(self, class_id: int | None, api_user: APIUser) -> str:
        """Retrieve the cluster name given the resource class id."""
        raise NotImplementedError()

    async def list_servers(self, safe_username: str) -> list[_SessionType]:
        """List all the user sessions visible from the safe_username."""
        raise NotImplementedError()

    async def create_server(
        self, manifest: _SessionType, api_user: AnonymousAPIUser | AuthenticatedAPIUser
    ) -> _SessionType:
        """Launch a user session."""
        raise NotImplementedError()

    async def get_server(self, name: str, safe_username: str) -> _SessionType | None:
        """Lookup a user session by name."""
        raise NotImplementedError()

    async def get_server_logs(
        self, server_name: str, safe_username: str, max_log_lines: Optional[int] = None
    ) -> dict[str, str]:
        """Retrieve the logs for the given user session."""
        raise NotImplementedError()

    async def patch_server(
        self, server_name: str, safe_username: str, patch: dict[str, Any] | list[dict[str, Any]]
    ) -> _SessionType:
        """Patch the user session."""
        raise NotImplementedError()

    async def delete_server(self, server_name: str, safe_username: str) -> None:
        """Delete the provided user session."""
        raise NotImplementedError()

    async def patch_server_tokens(self, server_name: str, renku_tokens: RenkuTokens, gitlab_token: GitlabToken) -> None:
        """Patch user authentication tokens in a user session."""
        raise NotImplementedError()

    async def patch_statefulset(
        self, server_name: str, patch: dict[str, Any] | list[dict[str, Any]]
    ) -> StatefulSet | None:
        """Patch a user session."""
        raise NotImplementedError()

    async def create_secret(self, secret: V1Secret) -> V1Secret:
        """Create a kubernetes secret."""
        raise NotImplementedError()

    async def delete_secret(self, name: str) -> None:
        """Delete a kubernetes secret."""
        raise NotImplementedError()
