import base64
import re
from dataclasses import dataclass, field
from json import JSONDecodeError
from pathlib import Path
from typing import Optional

import requests
from werkzeug.datastructures import WWWAuthenticate

from ...errors.user import ImageParseError


@dataclass
class ImageRepoDockerAPI:
    """Used to query the docker image repository API. Please note that all image repositories
    use this API, not just Dockerhub."""

    hostname: str
    oauth2_token: Optional[str] = field(default=None, repr=False)

    def _get_docker_token(self, image: "Image") -> Optional[str]:
        """
        Get an authorization token from the docker v2 API. This will return
        the token provided by the API (or None if no token was found).
        """
        image_digest_url = f"https://{self.hostname}/v2/{image.name}/manifests/{image.tag}"
        try:
            auth_req = requests.get(image_digest_url)
        except requests.ConnectionError:
            auth_req = None
        if auth_req is None or not (
            auth_req.status_code == 401 and "Www-Authenticate" in auth_req.headers.keys()
        ):
            # the request status code and header are not what is expected
            return None
        www_auth = WWWAuthenticate.from_header(auth_req.headers["Www-Authenticate"])
        params = {**www_auth.parameters}
        realm = params.pop("realm")
        headers = {}
        if self.oauth2_token:
            creds = base64.urlsafe_b64encode(f"oauth2:{self.oauth2_token}".encode()).decode()
            headers["Authorization"] = f"Basic {creds}"
        token_req = requests.get(realm, params=params, headers=headers)
        return token_req.json().get("token")

    def image_exists(self, image: "Image") -> bool:
        """Check the docker repo API if the image exists."""
        if image.hostname != self.hostname:
            raise ImageParseError(
                f"The image hostname {image.hostname} does not match "
                f"the image repository {self.hostname}"
            )
        token = self._get_docker_token(image)
        image_digest_url = f"https://{image.hostname}/v2/{image.name}/manifests/{image.tag}"
        headers = {"Accept": "application/vnd.docker.distribution.manifest.v2+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        auth_req = requests.get(image_digest_url, headers=headers)
        return auth_req.status_code == 200

    def image_workdir(self, image: "Image") -> Optional[Path]:
        """Query the docker API to get the workdir of an image."""
        if image.hostname != self.hostname:
            raise ImageParseError(
                f"The image hostname {image.hostname} does not match "
                f"the image repository {self.hostname}"
            )
        headers = {
            "Accept": "application/vnd.docker.distribution.manifest.v2+json",
        }
        token = self._get_docker_token(image)
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        try:
            res = requests.get(
                f"https://{image.hostname}/v2/{image.name}/manifests/{image.tag}", headers=headers
            )
        except requests.exceptions.ConnectionError:
            res = None
        if res is not None and res.status_code == 200:
            try:
                config_digest = res.json()["config"]["digest"]
            except (JSONDecodeError, KeyError):
                return None
            else:
                try:
                    res = requests.get(
                        f"https://{self.hostname}/v2/{image.name}/blobs/{config_digest}",
                        headers={
                            "Authorization": f"Bearer {token}",
                        }
                        if token is not None
                        else {},
                    )
                except requests.exceptions.ConnectionError:
                    res = None
                if res is not None and res.status_code == 200:
                    try:
                        working_dir = res.json()["config"]["WorkingDir"]
                    except (JSONDecodeError, KeyError):
                        return None
                    else:
                        return Path(working_dir)
        return None

    def with_oauth2_token(self, oauth2_token: str) -> "ImageRepoDockerAPI":
        return ImageRepoDockerAPI(self.hostname, oauth2_token)


@dataclass
class Image:
    hostname: str
    name: str
    tag: str

    @classmethod
    def from_path(cls, path: str):
        def build_re(*parts):
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
        regexes = [
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
            raise ImageParseError(
                f"Cannot parse the image {path}, too many interpretations {matches}"
            )
        else:
            raise ImageParseError(f"Cannot parse the image {path}")

    def repo_api(self) -> ImageRepoDockerAPI:
        return ImageRepoDockerAPI(self.hostname)
