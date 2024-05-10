"""An abstraction over the k8s client and the k8s-watcher."""

import base64
import json
import logging
from typing import Any, Optional
from urllib.parse import urljoin

import requests
from kubernetes import client
from kubernetes.client.exceptions import ApiException
from kubernetes.client.models import V1DeleteOptions
from kubernetes.config import load_config
from kubernetes.config.config_exception import ConfigException
from kubernetes.config.incluster_config import (
    SERVICE_CERT_FILENAME,
    SERVICE_TOKEN_FILENAME,
    InClusterConfigLoader,
)

from ...errors.intermittent import (
    CannotStartServerError,
    DeleteServerError,
    IntermittentError,
    JSCacheError,
    PatchServerError,
)
from ...errors.programming import ProgrammingError
from ...errors.user import MissingResourceError
from ...util.kubernetes_ import find_env_var
from ...util.retries import retry_with_exponential_backoff
from .auth import GitlabToken, RenkuTokens


class NamespacedK8sClient:
    def __init__(
        self,
        namespace: str,
        amalthea_group: str,
        amalthea_version: str,
        amalthea_plural: str,
    ):
        self.namespace = namespace
        self.amalthea_group = amalthea_group
        self.amalthea_version = amalthea_version
        self.amalthea_plural = amalthea_plural
        # NOTE: Try to load in-cluster config first, if that fails try to load kube config
        try:
            InClusterConfigLoader(
                token_filename=SERVICE_TOKEN_FILENAME,
                cert_filename=SERVICE_CERT_FILENAME,
            ).load_and_set()
        except ConfigException:
            load_config()
        self._custom_objects = client.CustomObjectsApi(client.ApiClient())
        self._custom_objects_patch = client.CustomObjectsApi(client.ApiClient())
        self._custom_objects_patch.api_client.set_default_header("Content-Type", "application/json-patch+json")
        self._core_v1 = client.CoreV1Api()
        self._apps_v1 = client.AppsV1Api()

    def _get_container_logs(
        self, pod_name: str, container_name: str, max_log_lines: Optional[int] = None
    ) -> Optional[str]:
        try:
            logs = self._core_v1.read_namespaced_pod_log(
                pod_name,
                self.namespace,
                container=container_name,
                tail_lines=max_log_lines,
                timestamps=True,
            )
        except ApiException as err:
            if err.status in [400, 404]:
                return  # container does not exist or is not ready yet
            else:
                raise IntermittentError(f"Logs cannot be read for pod {pod_name}, container {container_name}.")
        else:
            return logs

    def get_pod_logs(self, name: str, containers: list[str], max_log_lines: Optional[int] = None) -> dict[str, str]:
        output = {}
        for container in containers:
            logs = self._get_container_logs(pod_name=name, container_name=container, max_log_lines=max_log_lines)
            if logs:
                output[container] = logs
        return output

    def get_secret(self, name: str) -> Optional[dict[str, Any]]:
        try:
            secret = self._core_v1.read_namespaced_secret(name, self.namespace)
        except client.rest.ApiException:
            return None
        return secret

    def create_server(self, manifest: dict[str, Any]) -> dict[str, Any]:
        server_name = manifest.get("metadata", {}).get("name")
        try:
            self._custom_objects.create_namespaced_custom_object(
                group=self.amalthea_group,
                version=self.amalthea_version,
                namespace=self.namespace,
                plural=self.amalthea_plural,
                body=manifest,
            )
        except ApiException as e:
            logging.exception(f"Cannot start server {server_name} because of {e}")
            raise CannotStartServerError(
                message=f"Cannot start the session {server_name}",
            )
        # NOTE: We wait for the cache to sync with the newly created server
        # If not then the user will get a non-null response from the POST request but
        # then immediately after a null response because the newly created server has
        # not made it into the cache. With this we wait for the cache to catch up
        # before we send the response from the POST request out. Exponential backoff
        # is used to avoid overwhelming the cache.
        server = retry_with_exponential_backoff(lambda x: x is None)(self.get_server)(server_name)
        return server

    def patch_server(self, server_name: str, patch: dict[str, Any] | list[dict[str, Any]]):
        try:
            if isinstance(patch, list):  # noqa: SIM108
                # NOTE: The _custom_objects_patch will only accept rfc6902 json-patch.
                # We can recognize the type of patch because this is the only one that uses a list
                client = self._custom_objects_patch
            else:
                # NOTE: The _custom_objects will accept the usual rfc7386 merge patches
                client = self._custom_objects

            server = client.patch_namespaced_custom_object(
                group=self.amalthea_group,
                version=self.amalthea_version,
                namespace=self.namespace,
                plural=self.amalthea_plural,
                name=server_name,
                body=patch,
            )

        except ApiException as e:
            logging.exception(f"Cannot patch server {server_name} because of {e}")
            raise PatchServerError()

        return server

    def patch_statefulset(
        self, server_name: str, patch: dict[str, Any] | list[dict[str, Any]] | client.V1StatefulSet
    ) -> client.V1StatefulSet | None:
        try:
            ss = self._apps_v1.patch_namespaced_stateful_set(
                server_name,
                self.namespace,
                patch,
            )
        except ApiException as err:
            if err.status == 404:
                # NOTE: It can happen potentially that another request or something else
                # deleted the session as this request was going on, in this case we ignore
                # the missing statefulset
                return
            raise
        return ss

    def delete_server(self, server_name: str, forced: bool = False):
        try:
            status = self._custom_objects.delete_namespaced_custom_object(
                group=self.amalthea_group,
                version=self.amalthea_version,
                namespace=self.namespace,
                plural=self.amalthea_plural,
                name=server_name,
                grace_period_seconds=0 if forced else None,
                body=V1DeleteOptions(propagation_policy="Foreground"),
            )
        except ApiException as e:
            logging.exception(f"Cannot delete server {server_name} because of {e}")
            raise DeleteServerError()
        return status

    def get_server(self, name: str) -> Optional[dict[str, Any]]:
        """Get a specific JupyterServer object."""
        try:
            js = self._custom_objects.get_namespaced_custom_object(
                name=name,
                group=self.amalthea_group,
                version=self.amalthea_version,
                namespace=self.namespace,
                plural=self.amalthea_plural,
            )
        except ApiException as err:
            if err.status not in [400, 404]:
                logging.exception(f"Cannot get server {name} because of {err}")
                raise IntermittentError(f"Cannot get server {name} from the k8s API.")
            return
        return js

    def list_servers(self, label_selector: Optional[str] = None) -> list[dict[str, Any]]:
        """Get a list of k8s jupyterserver objects for a specific user."""
        try:
            jss = self._custom_objects.list_namespaced_custom_object(
                group=self.amalthea_group,
                version=self.amalthea_version,
                namespace=self.namespace,
                plural=self.amalthea_plural,
                label_selector=label_selector,
            )
        except ApiException as err:
            if err.status not in [400, 404]:
                logging.exception(f"Cannot list servers because of {err}")
                raise IntermittentError(f"Cannot list servers from the k8s API with selector {label_selector}.")
            return []
        return jss.get("items", [])

    def patch_image_pull_secret(self, server_name: str, gitlab_token: GitlabToken):
        """Patch the image pull secret used in a Renku session."""
        secret_name = f"{server_name}-image-secret"
        try:
            secret = self._core_v1.read_namespaced_secret(secret_name, self.namespace)
        except ApiException as err:
            if err.status == 404:
                # NOTE: In many cases the session does not have an image pull secret
                # this happens when the repo for the project is public so images are public
                return
            raise
        old_docker_config = json.loads(base64.b64decode(secret.data[".dockerconfigjson"]).decode())
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
        self._core_v1.patch_namespaced_secret(
            secret_name,
            self.namespace,
            patch,
        )

    def patch_statefulset_tokens(self, name: str, renku_tokens: RenkuTokens, gitlab_token: GitlabToken):
        """Patch the Renku and Gitlab access tokens that are used in the session statefulset."""
        try:
            ss = self._apps_v1.read_namespaced_stateful_set(name, self.namespace)
        except ApiException as err:
            if err.status == 404:
                # NOTE: It can happen potentially that another request or something else
                # deleted the session as this request was going on, in this case we ignore
                # the missing statefulset
                return
            raise
        if len(ss.spec.template.spec.containers) < 3 or len(ss.spec.template.spec.init_containers) < 3:
            raise ProgrammingError(
                "The expected setup for a session was not found when trying to inject new tokens",
                detail="Please contact a Renku administrator.",
            )
        git_proxy_container_index = 2
        git_proxy_container = ss.spec.template.spec.containers[git_proxy_container_index]
        secrets_init_container_index = 0
        secrets_init_container = ss.spec.template.spec.init_containers[secrets_init_container_index]
        git_init_container_index = 3
        git_init_container = ss.spec.template.spec.init_containers[git_init_container_index]
        patch = []
        expires_at_env = find_env_var(git_proxy_container, "GITLAB_OAUTH_TOKEN_EXPIRES_AT")
        gitlab_token_env = find_env_var(git_proxy_container, "GITLAB_OAUTH_TOKEN")
        git_init_token_env = find_env_var(git_init_container, "GIT_CLONE_USER__OAUTH_TOKEN")
        secrets_access_token_env = find_env_var(secrets_init_container, "RENKU_ACCESS_TOKEN")
        renku_access_token_env = find_env_var(git_proxy_container, "RENKU_ACCESS_TOKEN")
        renku_refresh_token_env = find_env_var(git_proxy_container, "RENKU_REFRESH_TOKEN")
        if not all(
            [
                expires_at_env,
                gitlab_token_env,
                git_init_token_env,
                secrets_access_token_env,
                renku_access_token_env,
                renku_refresh_token_env,
            ]
        ):
            raise ProgrammingError(
                "The expected environment variables were not found when trying to inject new tokens.",
                detail="Please contact a Renku administrator.",
            )
        patch = [
            {
                "op": "replace",
                "path": (
                    f"/spec/template/spec/containers/{git_proxy_container_index}" f"/env/{expires_at_env[0]}/value"
                ),
                "value": str(gitlab_token.expires_at),
            },
            {
                "op": "replace",
                "path": (
                    f"/spec/template/spec/containers/{git_proxy_container_index}" f"/env/{gitlab_token_env[0]}/value"
                ),
                "value": gitlab_token.access_token,
            },
            {
                "op": "replace",
                "path": (
                    f"/spec/template/spec/initContainers/{git_init_container_index}"
                    f"/env/{git_init_token_env[0]}/value"
                ),
                "value": gitlab_token.access_token,
            },
            {
                "op": "replace",
                "path": (
                    f"/spec/template/spec/initContainers/{secrets_init_container_index}"
                    f"/env/{secrets_access_token_env[0]}/value"
                ),
                "value": renku_tokens.access_token,
            },
            {
                "op": "replace",
                "path": (
                    f"/spec/template/spec/containers/{git_proxy_container_index}"
                    f"/env/{renku_access_token_env[0]}/value"
                ),
                "value": renku_tokens.access_token,
            },
            {
                "op": "replace",
                "path": (
                    f"/spec/template/spec/containers/{git_proxy_container_index}"
                    f"/env/{renku_refresh_token_env[0]}/value"
                ),
                "value": renku_tokens.refresh_token,
            },
        ]
        self._apps_v1.patch_namespaced_stateful_set(
            name,
            self.namespace,
            patch,
        )


class JsServerCache:
    def __init__(self, url: str):
        self.url = url

    def list_servers(self, safe_username: str) -> list[dict[str, Any]]:
        url = urljoin(self.url, f"/users/{safe_username}/servers")
        try:
            res = requests.get(url)
            res.raise_for_status()
        except requests.HTTPError as err:
            logging.warning(
                f"Listing servers at {url} from "
                f"jupyter server cache failed with status code: {res.status_code} "
                f"and error: {err}"
            )
            raise JSCacheError(f"The JSCache produced an unexpected status code: {err}") from err
        except requests.RequestException as err:
            logging.warning(f"Jupyter server cache at {url} cannot be reached: {err}")
            raise JSCacheError("The jupyter server cache is not available") from err
        return res.json()

    def get_server(self, name: str) -> Optional[dict[str, Any]]:
        url = urljoin(self.url, f"/servers/{name}")
        try:
            res = requests.get(url)
        except requests.exceptions.RequestException as err:
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
            return
        if len(output) > 1:
            raise ProgrammingError(f"Expected to find 1 server when getting server {name}, " f"found {len(output)}.")
        return output[0]


class K8sClient:
    def __init__(
        self,
        js_cache: JsServerCache,
        renku_ns_client: NamespacedK8sClient,
        username_label: str,
        session_ns_client: Optional[NamespacedK8sClient] = None,
    ):
        self.js_cache = js_cache
        self.renku_ns_client = renku_ns_client
        self.username_label = username_label
        self.session_ns_client = session_ns_client
        if not self.username_label:
            raise ProgrammingError("username_label has to be provided to K8sClient")

    def list_servers(self, safe_username: str) -> list[dict[str, Any]]:
        """Get a list of servers that belong to a user.

        Attempt to use the cache first but if the cache fails then use the k8s API.
        """
        try:
            return self.js_cache.list_servers(safe_username)
        except JSCacheError:
            logging.warning(f"Skipping the cache to list servers for user: {safe_username}")
            label_selector = f"{self.username_label}={safe_username}"
            return self.renku_ns_client.list_servers(label_selector) + (
                self.session_ns_client.list_servers(label_selector) if self.session_ns_client is not None else []
            )

    def get_server(self, name: str, safe_username: str) -> Optional[dict[str, Any]]:
        """Attempt to get a specific server by name from the cache.

        If the request to the cache fails, fallback to the k8s API.
        """
        server = None
        try:
            server = self.js_cache.get_server(name)
        except JSCacheError:
            output = []
            res = None
            if self.session_ns_client is not None:
                res = self.session_ns_client.get_server(name)
                if res:
                    output.append(res)
            res = self.renku_ns_client.get_server(name)
            if res:
                output.append(res)
            if len(output) > 1:
                raise ProgrammingError(
                    "Expected less than two results for searching for " f"server {name}, but got {len(output)}"
                )
            if len(output) == 0:
                return
            server = output[0]

        if server and server.get("metadata", {}).get("labels", {}).get(self.username_label) != safe_username:
            return
        return server

    def get_server_logs(
        self, server_name: str, safe_username: str, max_log_lines: Optional[int] = None
    ) -> dict[str, str]:
        server = self.get_server(server_name, safe_username)
        if server is None:
            raise MissingResourceError(
                f"Cannot find server {server_name} for user {safe_username} to read the logs from."
            )
        containers = list(server.get("status", {}).get("containerStates", {}).get("init", {}).keys()) + list(
            server.get("status", {}).get("containerStates", {}).get("regular", {}).keys()
        )
        namespace = server.get("metadata", {}).get("namespace")
        pod_name = f"{server_name}-0"
        if namespace == self.renku_ns_client.namespace:
            return self.renku_ns_client.get_pod_logs(pod_name, containers, max_log_lines)
        return self.session_ns_client.get_pod_logs(pod_name, containers, max_log_lines)

    def get_secret(self, name: str) -> Optional[dict[str, Any]]:
        if self.session_ns_client is not None:
            secret = self.session_ns_client.get_secret(name)
            if secret:
                return secret
        return self.renku_ns_client.get_secret(name)

    def create_server(self, manifest: dict[str, Any], safe_username: str):
        server_name = manifest.get("metadata", {}).get("name")
        server = self.get_server(server_name, safe_username)
        if server:
            # NOTE: server already exists
            return server
        if not self.session_ns_client:
            return self.renku_ns_client.create_server(manifest)
        return self.session_ns_client.create_server(manifest)

    def patch_server(self, server_name: str, safe_username: str, patch: dict[str, Any]):
        server = self.get_server(server_name, safe_username)
        if not server:
            raise MissingResourceError(
                f"Cannot find server {server_name} for user " f"{safe_username} in order to patch it."
            )

        namespace = server.get("metadata", {}).get("namespace")

        if namespace == self.renku_ns_client.namespace:
            return self.renku_ns_client.patch_server(server_name=server_name, patch=patch)
        else:
            return self.session_ns_client.patch_server(server_name=server_name, patch=patch)

    def patch_statefulset(self, server_name: str, patch: dict[str, Any]) -> client.V1StatefulSet | None:
        client = self.session_ns_client if self.session_ns_client else self.renku_ns_client
        return client.patch_statefulset(server_name=server_name, patch=patch)

    def delete_server(self, server_name: str, safe_username: str, forced: bool = False):
        server = self.get_server(server_name, safe_username)
        if not server:
            raise MissingResourceError(
                f"Cannot find server {server_name} for user " f"{safe_username} in order to delete it."
            )
        namespace = server.get("metadata", {}).get("namespace")
        if namespace == self.renku_ns_client.namespace:
            self.renku_ns_client.delete_server(server_name, forced)
        else:
            self.session_ns_client.delete_server(server_name, forced)

    def patch_tokens(self, server_name, renku_tokens: RenkuTokens, gitlab_token: GitlabToken):
        """Patch the Renku and Gitlab access tokens used in a session."""
        client = self.session_ns_client if self.session_ns_client else self.renku_ns_client
        client.patch_statefulset_tokens(server_name, renku_tokens, gitlab_token)
        client.patch_image_pull_secret(server_name, gitlab_token)

    @property
    def preferred_namespace(self) -> str:
        if self.session_ns_client is not None:
            return self.session_ns_client.namespace
        return self.renku_ns_client.namespace
