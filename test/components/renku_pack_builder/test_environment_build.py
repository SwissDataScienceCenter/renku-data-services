import subprocess
import time
from pathlib import Path

import pytest
import yaml


def kubectl_apply(namespace: str, manifest: str) -> subprocess.CompletedProcess:
    cmd = ["kubectl", "--namespace", namespace, "apply", "-f", manifest]
    return subprocess.run(cmd, capture_output=True)


def kubectl_delete(namespace: str, manifest: str) -> subprocess.CompletedProcess:
    cmd = ["kubectl", "--namespace", namespace, "delete", "--ignore-not-found", "-f", manifest]
    return subprocess.run(cmd, capture_output=True)


@pytest.fixture
def manifest_path() -> str:
    yield Path(__file__).parent / "../../../components/renku_pack_builder/manifests"


@pytest.fixture(scope="module")
def namespace() -> str:
    ns = "shipwright-tests"
    cmd = ["kubectl", "create", "namespace", ns]
    result = subprocess.run(cmd)
    assert result.returncode == 0

    yield ns

    cmd = ["kubectl", "delete", "namespace", ns]
    result = subprocess.run(cmd)
    assert result.returncode == 0


@pytest.fixture
def buildrun(manifest_path: str) -> str:
    yield manifest_path / "buildrun.yaml"


@pytest.fixture(autouse=True)
def setup_shipwrite_crds(namespace: str, manifest_path: str) -> None:
    manifests = ["buildstrategy.yaml", "build.yaml"]

    for manifest in manifests:
        result = kubectl_apply(namespace, manifest_path / manifest)
        assert result.returncode == 0

    yield

    for manifest in reversed(manifests):
        result = kubectl_delete(namespace, manifest_path / manifest)
        assert result.returncode == 0


@pytest.mark.skip(reason="current broken, fix this before releasing the shipwright feature")
def test_buildpacks_buildstrategy(namespace: str, buildrun: str) -> None:
    result = kubectl_apply(namespace, buildrun)
    assert result.returncode == 0

    with open(buildrun) as f:
        buildrun_content = yaml.safe_load(f)

    buildrun_name = buildrun_content.get("metadata", {}).get("name", None)
    cmd = [
        "kubectl",
        "--namespace",
        namespace,
        "get",
        "buildrun",
        buildrun_name,
        "-o",
        "jsonpath={.status.conditions[0]['reason']}",
    ]

    succeeded = False
    for i in range(5 * 60):
        result = subprocess.run(cmd, capture_output=True)
        assert result.returncode == 0

        succeeded = result.stdout == b"Succeeded"
        if succeeded:
            break
        time.sleep(1)

    kubectl_delete(namespace, buildrun)

    assert succeeded
