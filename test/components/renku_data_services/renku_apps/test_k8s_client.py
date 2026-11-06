"""Tests for the Renku apps k8s manifests."""

from pathlib import PurePosixPath
from types import SimpleNamespace
from typing import Any

import pytest
from ulid import ULID

from renku_data_services.renku_apps.k8s_client import _build_app_deployment_manifest, _build_data_connector_resources


def _data_connector(target_path: str) -> Any:
    storage = SimpleNamespace(
        source_path="bucket/folder",
        target_path=target_path,
        configuration={"type": "s3", "provider": "AWS"},
    )
    return SimpleNamespace(data_connector=SimpleNamespace(id=ULID(), name="my-data", storage=storage), secrets=[])


def _manifest_env(work_dir: PurePosixPath, volume_mounts: list[dict[str, Any]]) -> dict[str, str]:
    environment = SimpleNamespace(
        container_image="registry.example.org/app:1.0",
        port=8888,
        uid=1000,
        gid=1000,
        command=None,
        args=None,
        working_directory=work_dir,
    )
    launcher = SimpleNamespace(id=ULID(), environment=environment, env_variables=None)
    project = SimpleNamespace(id=ULID())
    manifest = _build_app_deployment_manifest(
        launcher,  # type: ignore[arg-type]
        "my-app",
        None,
        project,  # type: ignore[arg-type]
        labels={},
        work_dir=work_dir,
        volumes=[],
        volume_mounts=volume_mounts,
        affinity=None,
        tolerations=[],
    )
    container = manifest.model_dump(exclude_none=True, mode="json")["spec"]["template"]["spec"]["containers"][0]
    return {item["name"]: item["value"] for item in container["env"]}


@pytest.mark.parametrize("work_dir", [PurePosixPath("/home/renku/work"), PurePosixPath("/home/jovyan")])
def test_working_dir_env_var_is_the_data_connector_mount_base(work_dir: PurePosixPath) -> None:
    resources = _build_data_connector_resources(
        [_data_connector("my-data")],
        base_name="my-app-0123456789ab",
        namespace="renku",
        work_dir=work_dir,
        storage_class="csi-rclone",
        labels={},
    )
    volume_mounts = [r.volume_mount for r in resources]

    env = _manifest_env(work_dir, volume_mounts)

    assert env["RENKU_WORKING_DIR"] == work_dir.as_posix()
    assert volume_mounts[0]["mountPath"] == f"{env['RENKU_WORKING_DIR']}/my-data"


def test_mount_dir_and_cnb_app_dir_are_not_set() -> None:
    env = _manifest_env(PurePosixPath("/home/renku/work"), [])

    assert "RENKU_MOUNT_DIR" not in env
    assert "CNB_APP_DIR" not in env
