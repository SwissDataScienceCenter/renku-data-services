from dataclasses import asdict
from pathlib import PurePosixPath

import pytest

from renku_data_services.notebooks.api.classes.image import Image


@pytest.mark.parametrize(
    "name,expected",
    [
        (
            "nginx",
            {
                "hostname": "registry-1.docker.io",
                "name": "library/nginx",
                "tag": "latest",
            },
        ),
        (
            "nginx:1.28",
            {
                "hostname": "registry-1.docker.io",
                "name": "library/nginx",
                "tag": "1.28",
            },
        ),
        (
            "nginx@sha256:24235rt2rewg345ferwf",
            {
                "hostname": "registry-1.docker.io",
                "name": "library/nginx",
                "tag": "sha256:24235rt2rewg345ferwf",
            },
        ),
        (
            "username/image",
            {
                "hostname": "registry-1.docker.io",
                "name": "username/image",
                "tag": "latest",
            },
        ),
        (
            "username/image:1.0.0",
            {
                "hostname": "registry-1.docker.io",
                "name": "username/image",
                "tag": "1.0.0",
            },
        ),
        (
            "username/image@sha256:fdsaf345tre3412t1413r",
            {
                "hostname": "registry-1.docker.io",
                "name": "username/image",
                "tag": "sha256:fdsaf345tre3412t1413r",
            },
        ),
        (
            "gitlab.smth.com/username/project",
            {
                "hostname": "gitlab.smth.com",
                "name": "username/project",
                "tag": "latest",
            },
        ),
        (
            "gitlab.smth.com:443/username/project",
            {
                "hostname": "gitlab.smth.com:443",
                "name": "username/project",
                "tag": "latest",
            },
        ),
        (
            "gitlab.smth.com/username/project/image/subimage",
            {
                "hostname": "gitlab.smth.com",
                "name": "username/project/image/subimage",
                "tag": "latest",
            },
        ),
        (
            "gitlab.smth.com:443/username/project/image/subimage",
            {
                "hostname": "gitlab.smth.com:443",
                "name": "username/project/image/subimage",
                "tag": "latest",
            },
        ),
        (
            "gitlab.smth.com/username/project:1.2.3",
            {
                "hostname": "gitlab.smth.com",
                "name": "username/project",
                "tag": "1.2.3",
            },
        ),
        (
            "gitlab.smth.com:443/username/project:1.2.3",
            {
                "hostname": "gitlab.smth.com:443",
                "name": "username/project",
                "tag": "1.2.3",
            },
        ),
        (
            "gitlab.smth.com/username/project/image/subimage:1.2.3",
            {
                "hostname": "gitlab.smth.com",
                "name": "username/project/image/subimage",
                "tag": "1.2.3",
            },
        ),
        (
            "gitlab.smth.com:443/username/project/image/subimage:1.2.3",
            {
                "hostname": "gitlab.smth.com:443",
                "name": "username/project/image/subimage",
                "tag": "1.2.3",
            },
        ),
        (
            "gitlab.smth.com/username/project@sha256:324fet13t4",
            {
                "hostname": "gitlab.smth.com",
                "name": "username/project",
                "tag": "sha256:324fet13t4",
            },
        ),
        (
            "gitlab.smth.com:443/username/project@sha256:324fet13t4",
            {
                "hostname": "gitlab.smth.com:443",
                "name": "username/project",
                "tag": "sha256:324fet13t4",
            },
        ),
        (
            "gitlab.smth.com/username/project/image/subimage@sha256:324fet13t4",
            {
                "hostname": "gitlab.smth.com",
                "name": "username/project/image/subimage",
                "tag": "sha256:324fet13t4",
            },
        ),
        (
            "gitlab.smth.com:443/username/project/image/subimage@sha256:324fet13t4",
            {
                "hostname": "gitlab.smth.com:443",
                "name": "username/project/image/subimage",
                "tag": "sha256:324fet13t4",
            },
        ),
        (
            "us.gcr.io/image/subimage@sha256:324fet13t4",
            {
                "hostname": "us.gcr.io",
                "name": "image/subimage",
                "tag": "sha256:324fet13t4",
            },
        ),
        (
            "us.gcr.io/proj/image",
            {"hostname": "us.gcr.io", "name": "proj/image", "tag": "latest"},
        ),
        (
            "us.gcr.io/proj/image/subimage",
            {"hostname": "us.gcr.io", "name": "proj/image/subimage", "tag": "latest"},
        ),
    ],
)
def test_public_image_name_parsing(name: str, expected: dict[str, str]) -> None:
    assert asdict(Image.from_path(name)) == expected


@pytest.mark.parametrize(
    "image,exists_expected",
    [
        ("nginx:1.19.3", True),
        ("nginx", True),
        ("renku/singleuser:cb70d7e", True),
        ("renku/singleuser", True),
        ("madeuprepo/madeupproject:tag", False),
        ("olevski90/oci-image:0.0.1", True),
        ("ghcr.io/linuxserver/nginx:latest", True),
    ],
)
@pytest.mark.asyncio
@pytest.mark.integration
async def test_public_image_check(image: str, exists_expected: bool) -> None:
    parsed_image = Image.from_path(image)
    exists_observed = await parsed_image.repo_api().image_exists(parsed_image)
    assert exists_expected == exists_observed


@pytest.mark.parametrize(
    "image,expected_path",
    [
        ("jupyter/minimal-notebook:x86_64-python-3.11.6", PurePosixPath("/home/jovyan")),
        ("nginx", PurePosixPath("/")),
        ("nginx@sha256:367678a80c0be120f67f3adfccc2f408bd2c1319ed98c1975ac88e750d0efe26", PurePosixPath("/")),
        ("madeuprepo/madeupproject:tag", None),
    ],
)
@pytest.mark.asyncio
@pytest.mark.integration
async def test_image_workdir_check(image: str, expected_path: PurePosixPath | None) -> None:
    parsed_image = Image.from_path(image)
    workdir = await parsed_image.repo_api().image_workdir(parsed_image)
    if expected_path is None:
        assert workdir is None, f"The image workdir should be None but instead it is {workdir}"
    else:
        assert workdir == expected_path
