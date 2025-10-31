import json
import os
import subprocess
from contextlib import AbstractContextManager
from typing import Any

import yaml
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes import watch
from sanic import Request
from sanic_testing.testing import SanicASGITestClient, TestingResponse

from renku_data_services.base_models import APIUser
from renku_data_services.users.models import UserInfo


async def create_rp(payload: dict[str, Any], test_client: SanicASGITestClient) -> tuple[Request, TestingResponse]:
    return await test_client.post(
        "/api/data/resource_pools",
        headers={"Authorization": 'Bearer {"is_admin": true}'},
        data=json.dumps(payload),
    )


async def create_user_preferences(
    test_client: SanicASGITestClient, valid_add_pinned_project_payload: dict[str, Any], api_user: APIUser
) -> tuple[Request, TestingResponse]:
    """Create user preferences by adding a pinned project"""
    return await test_client.post(
        "/api/data/user/preferences/pinned_projects",
        headers={"Authorization": f"bearer {api_user.access_token}"},
        data=json.dumps(valid_add_pinned_project_payload),
    )


async def create_user_preferences_dismiss_banner(
    test_client: SanicASGITestClient, api_user: APIUser
) -> tuple[Request, TestingResponse]:
    """Create user preferences by dismiss migration project banner"""
    return await test_client.post(
        "/api/data/user/preferences/dismiss_project_migration_banner",
        headers={"Authorization": f"bearer {api_user.access_token}"},
    )


def merge_headers(*headers: dict[str, str]) -> dict[str, str]:
    """Merge multiple headers."""
    all_headers = dict()
    for h in headers:
        all_headers.update(**h)
    return all_headers


def dataclass_to_str(object) -> str:
    """Convert a dataclass to str to make them hashable."""
    data = object.asdict()
    return json.dumps(data, sort_keys=True, default=str)


class KindCluster(AbstractContextManager):
    """Context manager that will create and tear down a k3s cluster"""

    def __init__(
        self,
        cluster_name: str,
        kubeconfig=".kind-kubeconfig.yaml",
        extra_images: list[str] | None = None,
    ):
        self.cluster_name = cluster_name
        if extra_images is None:
            extra_images = []
        self.extra_images = extra_images
        self.kubeconfig = kubeconfig
        self.env = os.environ.copy()
        self.env["KUBECONFIG"] = self.kubeconfig

    def __enter__(self):
        """create kind cluster"""

        create_cluster = [
            "kind",
            "create",
            "cluster",
            "--name",
            self.cluster_name,
            "--kubeconfig",
            self.kubeconfig,
        ]

        try:
            subprocess.run(create_cluster, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=self.env, check=True)
        except subprocess.SubprocessError as err:
            if err.output is not None:
                print(err.output.decode())
            else:
                print(err)
            raise

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """delete kind cluster"""

        self._delete_cluster()
        return False

    def _delete_cluster(self):
        """delete kind cluster"""

        delete_cluster = ["kind", "delete", "cluster", "--name", self.cluster_name, "--kubeconfig", self.kubeconfig]
        subprocess.run(delete_cluster, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=self.env, check=True)

    def config_yaml(self):
        with open(self.kubeconfig) as f:
            return f.read()


def setup_amalthea(install_name: str, app_name: str, version: str, cluster: KindCluster) -> None:
    k8s_config.load_kube_config_from_dict(yaml.safe_load(cluster.config_yaml()))

    core_api = k8s_client.CoreV1Api()

    helm_cmds = [
        ["helm", "repo", "add", "renku", "https://swissdatasciencecenter.github.io/helm-charts"],
        ["helm", "repo", "update"],
        ["helm", "upgrade", "--install", install_name, f"renku/{app_name}", "--version", version, "--wait"],
    ]

    for cmd in helm_cmds:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=cluster.env, check=True)

    watcher = watch.Watch()

    for event in watcher.stream(
        core_api.list_namespaced_pod,
        label_selector=f"app.kubernetes.io/name={app_name}",
        namespace="default",
        timeout_seconds=60,
    ):
        if event["object"].status.phase == "Running":
            watcher.stop()
            break
    else:
        raise AssertionError("Timeout waiting on amalthea to run") from None


def create_api_user_from_user_info(user: UserInfo, access_token: str, is_admin: bool = False) -> APIUser:
    return APIUser(
        id=user.id,
        access_token=access_token,
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email,
        is_admin=is_admin,
    )
