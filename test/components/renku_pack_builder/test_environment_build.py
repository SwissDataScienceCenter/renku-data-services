import pytest
import subprocess
import time

from pathlib import Path


def kubectl_apply(manifest: str) -> subprocess.CompletedProcess:
    cmd = ["kubectl", "apply", "-f", manifest]
    return subprocess.run(cmd, capture_output=True)


def kubectl_delete(manifest: str) -> subprocess.CompletedProcess:
    cmd = ["kubectl", "delete", "--ignore-not-found", "-f", manifest]
    return subprocess.run(cmd, capture_output=True)


@pytest.fixture
def manifest_path() -> str:
    yield Path(__file__).parent / "../../../components/renku_pack_builder/manifests"


@pytest.fixture
def buildrun(manifest_path: str) -> str:
    yield manifest_path / "buildrun.yaml"


@pytest.fixture(autouse=True)
def setup_shipwrite_crds(manifest_path: str) -> None:
    manifests = ["buildstrategy_buildpacks.yaml", "build.yaml"]

    for manifest in manifests:
        result = kubectl_apply(manifest_path / manifest)
        assert result.returncode == 0

    yield

    for manifest in reversed(manifests):
        result = kubectl_delete(manifest_path / manifest)
        assert result.returncode == 0


def test_buildpacks_buildstrategy(buildrun: str) -> None:
    result = kubectl_apply(buildrun)
    assert result.returncode == 0

    cmd = ["kubectl", "get", "buildrun", "buildpack-python-env-3", "-o", "jsonpath={.status.conditions[0]['reason']}"]

    succeeded = False
    for i in range(5 * 60):
        result = subprocess.run(cmd, capture_output=True)
        assert result.returncode == 0

        succeeded = result.stdout == b"Succeeded"
        if succeeded:
            break
        time.sleep(1)

    kubectl_delete(buildrun)

    assert succeeded
