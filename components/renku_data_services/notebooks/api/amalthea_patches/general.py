from typing import TYPE_CHECKING

from ...config import config
from ..classes.user import RegisteredUser

if TYPE_CHECKING:
    from renku_notebooks.api.classes.server import UserServer


def session_tolerations(server: "UserServer"):
    """Patch for node taint tolerations, the static tolerations from the configuration are ignored
    if the tolerations are set in the server options (coming from CRC)."""
    if not server.server_options.tolerations:
        key = f"{config.session_get_endpoint_annotations.renku_annotation_prefix}dedicated"
        tolerations = [
            {
                "key": key,
                "operator": "Equal",
                "value": "user",
                "effect": "NoSchedule",
            },
        ] + config.sessions.tolerations
        return [
            {
                "type": "application/json-patch+json",
                "patch": [
                    {
                        "op": "add",
                        "path": "/statefulset/spec/template/spec/tolerations",
                        "value": tolerations,
                    }
                ],
            }
        ]
    return [i.json_patch() for i in server.server_options.tolerations]


def session_affinity(server: "UserServer"):
    """Patch for session affinities, the static affinities from the configuration are ignored
    if the affinities are set in the server options (coming from CRC)."""
    if not server.server_options.node_affinities:
        return [
            {
                "type": "application/json-patch+json",
                "patch": [
                    {
                        "op": "add",
                        "path": "/statefulset/spec/template/spec/affinity",
                        "value": config.sessions.affinity,
                    }
                ],
            }
        ]
    return [i.json_patch() for i in server.server_options.node_affinities]


def session_node_selector(server: "UserServer"):
    """Patch for a node selector, if node affinities are specified in the server options
    (coming from CRC) node selectors in the static configuration are ignored."""
    if not server.server_options.node_affinities:
        return [
            {
                "type": "application/json-patch+json",
                "patch": [
                    {
                        "op": "add",
                        "path": "/statefulset/spec/template/spec/nodeSelector",
                        "value": config.sessions.node_selector,
                    }
                ],
            }
        ]
    return []


def priority_class(server: "UserServer"):
    if server.server_options.priority_class is None:
        return []
    return [
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/priorityClassName",
                    "value": server.server_options.priority_class,
                }
            ],
        }
    ]


def test(server: "UserServer"):
    """RFC 6901 patches support test statements that will cause the whole patch
    to fail if the test statements are not correct. This is used to ensure that the
    order of containers in the amalthea manifests is what the notebook service expects.
    """
    patches = []
    # NOTE: Only the first 1 or 2 containers come "included" from Amalthea, the rest are patched in
    # This tests checks whether the expected number and order is received from Amalthea and
    # does not use all containers.
    container_names = (
        config.sessions.containers.registered[:2]
        if type(server._user) is RegisteredUser
        else config.sessions.containers.anonymous[:1]
    )
    for container_ind, container_name in enumerate(container_names):
        patches.append(
            {
                "type": "application/json-patch+json",
                "patch": [
                    {
                        "op": "test",
                        "path": (
                            "/statefulset/spec/template/spec" f"/containers/{container_ind}/name"
                        ),
                        "value": container_name,
                    }
                ],
            }
        )
    return patches


def oidc_unverified_email(server: "UserServer"):
    patches = []
    if type(server._user) is RegisteredUser:
        # modify oauth2 proxy to accept users whose email has not been verified
        # usually enabled for dev purposes
        patches.append(
            {
                "type": "application/json-patch+json",
                "patch": [
                    {
                        "op": "add",
                        "path": "/statefulset/spec/template/spec/containers/1/env/-",
                        "value": {
                            "name": "OAUTH2_PROXY_INSECURE_OIDC_ALLOW_UNVERIFIED_EMAIL",
                            "value": str(config.sessions.oidc.allow_unverified_email).lower(),
                        },
                    },
                ],
            }
        )
    return patches
