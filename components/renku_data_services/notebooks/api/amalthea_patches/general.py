from typing import TYPE_CHECKING

from flask import current_app

from ..classes.user import RegisteredUser

if TYPE_CHECKING:
    from renku_notebooks.api.classes.server import UserServer


def session_tolerations():
    patches = []
    tolerations = [
        {
            "key": f"{current_app.config['RENKU_ANNOTATION_PREFIX']}dedicated",
            "operator": "Equal",
            "value": "user",
            "effect": "NoSchedule",
        },
        *current_app.config["SESSION_TOLERATIONS"],
    ]
    patches.append(
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
    )
    return patches


def termination_grace_period():
    return [
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/terminationGracePeriodSeconds",
                    "value": current_app.config[
                        "SESSION_TERMINATION_GRACE_PERIOD_SECONDS"
                    ],
                }
            ],
        }
    ]


def session_affinity():
    return [
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/affinity",
                    "value": current_app.config["SESSION_AFFINITY"],
                }
            ],
        }
    ]


def session_node_selector():
    return [
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/nodeSelector",
                    "value": current_app.config["SESSION_NODE_SELECTOR"],
                }
            ],
        }
    ]


def test(server: "UserServer"):
    """RFC 6901 patches support test statements that will cause the whole patch
    to fail if the test statements are not correct. This is used to ensure that the
    order of containers in the amalthea manifests is what the notebook service expects."""
    patches = []
    container_names = (
        current_app.config["AMALTHEA_CONTAINER_ORDER_REGISTERED_SESSION"]
        if type(server._user) is RegisteredUser
        else current_app.config["AMALTHEA_CONTAINER_ORDER_ANONYMOUS_SESSION"]
    )
    for container_ind, container_name in enumerate(container_names):
        patches.append(
            {
                "type": "application/json-patch+json",
                "patch": [
                    {
                        "op": "test",
                        "path": (
                            "/statefulset/spec/template/spec"
                            f"/containers/{container_ind}/name"
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
                            "value": current_app.config["OIDC_ALLOW_UNVERIFIED_EMAIL"],
                        },
                    },
                ],
            }
        )
    return patches
