"""Used to get information about docker images used in jupyter servers."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Optional, Self, cast

import httpx
from werkzeug.datastructures import WWWAuthenticate

from renku_data_services.app_config import logging
from renku_data_services.errors import errors

logger = logging.getLogger(__name__)


class ManifestTypes(Enum):
    """The mime types for docker image manifests."""

    docker_v2 = "application/vnd.docker.distribution.manifest.v2+json"
    docker_v2_list = "application/vnd.docker.distribution.manifest.list.v2+json"
    oci_v1_manifest = "application/vnd.oci.image.manifest.v1+json"
    oci_v1_index = "application/vnd.oci.image.index.v1+json"


DEFAULT_PLATFORM_ARCHITECTURE = "amd64"
DEFAULT_PLATFORM_OS = "linux"


@dataclass
class ImageRepoDockerAPI:
    """Used to query the docker image repository API.

    Please note that all image repositories use this API, not just Dockerhub.
    """

    hostname: str
    oauth2_token: Optional[str] = field(default=None, repr=False)

    # NOTE: We need to follow redirects so that we can authenticate with the image repositories properly.
    # NOTE: If we do not use default_factory to create the client here requests will fail because it can happen
    # that the client gets created in the wrong asyncio loop.
    client: httpx.AsyncClient = field(default_factory=lambda: httpx.AsyncClient(timeout=10, follow_redirects=True))
    scheme: str = "https"

    def __post_init__(self) -> None:
        self.hostname = self.hostname.rstrip("/")
        if self.scheme == "":
            self.scheme = "https"

    async def _get_docker_token(self, image: Image) -> Optional[str]:
        """Get an authorization token from the docker v2 API.

        This will return the token provided by the API (or None if no token was found).
        """
        image_digest_url = f"{self.scheme}://{self.hostname}/v2/{image.name}/manifests/{image.tag}"
        try:
            auth_req = await self.client.get(image_digest_url)
        except httpx.ConnectError:
            auth_req = None
        if auth_req is None or not (auth_req.status_code == 401 and "Www-Authenticate" in auth_req.headers):
            # the request status code and header are not what is expected
            return None
        www_auth = WWWAuthenticate.from_header(auth_req.headers["Www-Authenticate"])
        if not www_auth:
            return None
        params = {**www_auth.parameters}
        realm = params.pop("realm")
        if not realm:
            return None
        headers = {"Accept": "application/json"}
        if self.oauth2_token:
            creds = base64.b64encode(f"oauth2:{self.oauth2_token}".encode()).decode()
            headers["Authorization"] = f"Basic {creds}"
        token_req = await self.client.get(realm, params=params, headers=headers)
        return str(token_req.json().get("token"))

    async def get_image_manifest(
        self,
        image: Image,
        platform_architecture: str = DEFAULT_PLATFORM_ARCHITECTURE,
        platform_os: str = DEFAULT_PLATFORM_OS,
    ) -> Optional[dict[str, Any]]:
        """Query the docker API to get the manifest of an image."""
        if image.hostname != self.hostname:
            raise errors.ValidationError(
                message=f"The image hostname {image.hostname} does not match the image repository {self.hostname}"
            )
        token = await self._get_docker_token(image)
        image_digest_url = f"{self.scheme}://{image.hostname}/v2/{image.name}/manifests/{image.tag}"
        headers = {"Accept": ManifestTypes.docker_v2.value}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        res = await self.client.get(image_digest_url, headers=headers)
        if res.status_code != 200:
            headers["Accept"] = ManifestTypes.oci_v1_manifest.value
            res = await self.client.get(image_digest_url, headers=headers)
        if res.status_code != 200:
            headers["Accept"] = ManifestTypes.oci_v1_index.value
            res = await self.client.get(image_digest_url, headers=headers)
        if res.status_code != 200:
            return None

        content_type = res.headers.get("Content-Type")
        if content_type in [ManifestTypes.docker_v2_list.value, ManifestTypes.oci_v1_index.value]:
            index_parsed = res.json()

            def platform_matches(manifest: dict[str, Any]) -> bool:
                platform: dict[str, Any] = manifest.get("platform", {})
                return platform.get("architecture") == platform_architecture and platform.get("os") == platform_os

            manifest: dict[str, Any] = next(filter(platform_matches, index_parsed.get("manifests", [])), {})
            image_digest: str | None = manifest.get("digest")
            if not manifest or not image_digest:
                return None
            image_digest_url = f"{self.scheme}://{image.hostname}/v2/{image.name}/manifests/{image_digest}"
            media_type = manifest.get("mediaType")
            headers["Accept"] = ManifestTypes.docker_v2.value
            if media_type in [
                ManifestTypes.docker_v2.value,
                ManifestTypes.oci_v1_manifest.value,
            ]:
                headers["Accept"] = media_type
            res = await self.client.get(image_digest_url, headers=headers)
            if res.status_code != 200:
                headers["Accept"] = ManifestTypes.oci_v1_manifest.value
                res = await self.client.get(image_digest_url, headers=headers)
            if res.status_code != 200:
                return None

        if res.headers.get("Content-Type") not in [
            ManifestTypes.docker_v2.value,
            ManifestTypes.oci_v1_manifest.value,
        ]:
            return None

        return cast(dict[str, Any], res.json())

    async def image_exists(self, image: Image) -> bool:
        """Check the docker repo API if the image exists."""
        return await self.image_check(image) == 200

    async def image_check(self, image: Image) -> int:
        """Check the image at the registry."""
        token = await self._get_docker_token(image)
        image_digest_url = f"{self.scheme}://{image.hostname}/v2/{image.name}/manifests/{image.tag}"
        accept_media = ",".join(
            [e.value for e in [ManifestTypes.docker_v2, ManifestTypes.oci_v1_manifest, ManifestTypes.oci_v1_index]]
        )
        headers = {"Accept": accept_media}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        res = await self.client.head(image_digest_url, headers=headers)
        logger.debug(f"Checked image access: {image_digest_url}: {res.status_code}")
        return res.status_code

    async def get_image_config(self, image: Image) -> Optional[dict[str, Any]]:
        """Query the docker API to get the configuration of an image."""
        manifest = await self.get_image_manifest(image)
        if manifest is None:
            return None
        config_digest = manifest.get("config", {}).get("digest")
        if config_digest is None:
            return None
        token = await self._get_docker_token(image)
        res = await self.client.get(
            f"{self.scheme}://{image.hostname}/v2/{image.name}/blobs/{config_digest}",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )
        if res.status_code != 200:
            return None
        return cast(dict[str, Any], res.json())

    async def image_workdir(self, image: Image) -> Optional[PurePosixPath]:
        """Query the docker API to get the workdir of an image."""
        config = await self.get_image_config(image)
        if config is None:
            return None
        nested_config = config.get("config", {})
        if nested_config is None:
            return None
        workdir = nested_config.get("WorkingDir", "/")
        if workdir == "":
            workdir = "/"
        return PurePosixPath(workdir)

    def with_oauth2_token(self, oauth2_token: str) -> ImageRepoDockerAPI:
        """Return a docker API instance with the token as authentication."""
        return ImageRepoDockerAPI(hostname=self.hostname, scheme=self.scheme, oauth2_token=oauth2_token)

    def maybe_with_oauth2_token(self, token_hostname: str | None, oauth2_token: str | None) -> ImageRepoDockerAPI:
        """Return a docker API instance with the token as authentication.

        The token is used only if the image hostname matches the token hostname.
        """
        if isinstance(token_hostname, str) and self.hostname == token_hostname and oauth2_token:
            return ImageRepoDockerAPI(self.hostname, oauth2_token)
        else:
            return self


@dataclass
class Image:
    """Representation of a docker image."""

    hostname: str
    name: str
    tag: str

    @classmethod
    def from_path(cls, path: str) -> Self:
        """Create an image from a path like 'nginx:1.28'."""

        def build_re(*parts: str) -> re.Pattern:
            """Assemble the regex."""
            return re.compile(r"^" + r"".join(parts) + r"$")

        hostname = r"(?P<hostname>(?<=^)[a-zA-Z0-9_\-]{1,}\.[a-zA-Z0-9\._\-:]{1,}(?=\/))"
        docker_username = r"(?P<username>(?<=^)[a-zA-Z0-9]{1,}(?=\/))"
        username = r"(?P<username>(?<=\/)[a-zA-Z0-9\._\-]{1,}(?=\/))"
        docker_image = r"(?P<image>(?:(?<=\/)|(?<=^))[a-zA-Z0-9\._\-]{1,}(?:(?=:)|(?=@)|(?=$)))"
        image = r"(?P<image>(?:(?<=\/)|(?<=^))[a-zA-Z0-9\._\-\/]{1,}(?:(?=:)|(?=@)|(?=$)))"
        sha = r"(?P<tag>(?<=@)[a-zA-Z0-9\._\-:]{1,}(?=$))"
        tag = r"(?P<tag>(?<=:)[a-zA-Z0-9\._\-]{1,}(?=$))"

        # a list of tuples with (regex, defaults to fill in case of match)
        regexes: list[tuple[re.Pattern, dict[str, str]]] = [
            # nginx
            (
                build_re(docker_image),
                {
                    "hostname": "registry-1.docker.io",
                    "username": "library",
                    "tag": "latest",
                },
            ),
            # username/image
            (
                build_re(docker_username, r"\/", docker_image),
                {"hostname": "registry-1.docker.io", "tag": "latest"},
            ),
            # nginx:1.28
            (
                build_re(docker_image, r":", tag),
                {"hostname": "registry-1.docker.io", "username": "library"},
            ),
            # username/image:1.0.0
            (
                build_re(docker_username, r"\/", docker_image, r":", tag),
                {"hostname": "registry-1.docker.io"},
            ),
            # nginx@sha256:24235rt2rewg345ferwf
            (
                build_re(docker_image, r"@", sha),
                {"hostname": "registry-1.docker.io", "username": "library"},
            ),
            # username/image@sha256:fdsaf345tre3412t1413r
            (
                build_re(docker_username, r"\/", docker_image, r"@", sha),
                {"hostname": "registry-1.docker.io"},
            ),
            # gitlab.com/username/project
            # gitlab.com/username/project/image/subimage
            (build_re(hostname, r"\/", username, r"\/", image), {"tag": "latest"}),
            # gitlab.com/username/project:1.2.3
            # gitlab.com/username/project/image/subimage:1.2.3
            (build_re(hostname, r"\/", username, r"\/", image, r":", tag), {}),
            # gitlab.com/username/project@sha256:324fet13t4
            # gitlab.com/username/project/image/subimage@sha256:324fet13t4
            (build_re(hostname, r"\/", username, r"\/", image, r"@", sha), {}),
        ]

        matches = []
        for regex, fill in regexes:
            match = regex.match(path)
            if match is not None:
                match_dict = match.groupdict()
                match_dict.update(fill)
                # lump username in image name - not required to have it separate
                # however separating these in the regex makes it easier to match
                match_dict["image"] = match_dict["username"] + "/" + match_dict["image"]
                match_dict.pop("username")
                matches.append(match_dict)
        if len(matches) == 1:
            return cls(matches[0]["hostname"], matches[0]["image"], matches[0]["tag"])
        elif len(matches) > 1:
            raise errors.ValidationError(message=f"Cannot parse the image {path}, too many interpretations {matches}")
        else:
            raise errors.ValidationError(message=f"Cannot parse the image {path}")

    def repo_api(self) -> ImageRepoDockerAPI:
        """Get the docker API from the image."""
        return ImageRepoDockerAPI(self.hostname)

    def __str__(self) -> str:
        return f"{self.hostname}/{self.name}:{self.tag}"
