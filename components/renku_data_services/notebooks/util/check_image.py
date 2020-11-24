import base64
import re
import requests

from .. import config
from .gitlab_ import _get_oauth_token
from werkzeug.http import parse_www_authenticate_header


def get_docker_token(hostname, image, tag, user):
    """
    Get a authorization token from the docker v2 API. This will return
    the token provided by the API (or None if no token was found). In
    addition it will also provide an indication of whether the token
    is for a private image (True) or if it is for a public one (False).
    """
    image_digest_url = f"https://{hostname}/v2/{image}/manifests/{tag}"
    auth_req = requests.get(image_digest_url)
    if not (
        auth_req.status_code == 401 and "Www-Authenticate" in auth_req.headers.keys()
    ):
        # the request status code and header are not what is expected
        return None, None
    www_auth = parse_www_authenticate_header(auth_req.headers["Www-Authenticate"])
    params = dict(www_auth.items())
    realm = params.pop("realm")
    # try to get a public docker token
    token_req = requests.get(realm, params=params)
    public_token = token_req.json().get("token")
    if public_token is not None:
        return public_token, False
    # try to get private token by authenticating
    # ensure that you won't send oauth token somewhere randomly
    if (
        re.match(
            r"^" + re.escape(f"https://{config.IMAGE_REGISTRY}") + r".*",
            image_digest_url,
        )
        is not None
    ):
        oauth_token = _get_oauth_token(user)
        creds = base64.urlsafe_b64encode(f"oauth2:{oauth_token}".encode()).decode()
        token_req = requests.get(
            realm, params=params, headers={"Authorization": f"Basic {creds}"}
        )
        private_token = token_req.json().get("token")
        if private_token is not None:
            return private_token, True
    return None, None


def image_exists(hostname, image, tag, token=None):
    """Check the docker repo API if the image exists and if it is public or not."""
    image_digest_url = f"https://{hostname}/v2/{image}/manifests/{tag}"
    pub_req = requests.get(
        image_digest_url,
        headers={"Accept": "application/vnd.docker.distribution.manifest.v2+json"},
    )
    if pub_req.status_code == 200:
        # the repo did not require authentication
        return True
    if (
        pub_req.status_code == 401
        and "Www-Authenticate" in pub_req.headers.keys()
        and token is not None
    ):
        # the repo requires a token, try to use provided token
        auth_req = requests.get(
            image_digest_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.docker.distribution.manifest.v2+json",
            },
        )
        return auth_req.status_code == 200
    return False


def build_re(*parts):
    """Assemble the regex."""
    return re.compile(r"^" + r"".join(parts) + r"$")


def parse_image_name(image_name):
    """
    Extract the hostname, image and tag name from the provided
    string. If the image cannot be validated return None. Otherwise return
    a dictionary with the keys ['hostname', 'image', 'tag'].
    """
    hostname = r"(?P<hostname>(?<=^)[a-zA-Z0-9_\-]{1,}\.[a-zA-Z0-9\._\-:]{1,}(?=\/))"
    docker_username = r"(?P<username>(?<=^)[a-zA-Z0-9]{1,}(?=\/))"
    username = r"(?P<username>(?<=\/)[a-zA-Z0-9\._\-]{1,}(?=\/))"
    docker_image = (
        r"(?P<image>(?:(?<=\/)|(?<=^))[a-zA-Z0-9\._\-]{1,}(?:(?=:)|(?=@)|(?=$)))"
    )
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
        match = regex.match(image_name)
        if match is not None:
            match_dict = match.groupdict()
            match_dict.update(fill)
            # lump username in image name - not required to have it separate
            # however separating these in the regex makes it easier to match
            match_dict["image"] = match_dict["username"] + "/" + match_dict["image"]
            match_dict.pop("username")
            matches.append(match_dict)
    if len(matches) == 1:
        return matches[0]
