"""General patches for the jupyter server session."""

from __future__ import annotations

from numbers import Number
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # NOTE: If these are directly imported then you get circular imports.
    from renku_data_services.notebooks.api.classes.server import UserServer


def session_tolerations(server: UserServer) -> list[dict[str, Any]]:
    """Patch for node taint tolerations.

    The static tolerations from the configuration are ignored
    if the tolerations are set in the server options (coming from CRC).
    """
    key = f"{server.config.session_get_endpoint_annotations.renku_annotation_prefix}dedicated"
    default_tolerations: list[dict[str, str]] = [
        {
            "key": key,
            "operator": "Equal",
            "value": "user",
            "effect": "NoSchedule",
        },
    ] + server.config.sessions.tolerations
    return [
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/tolerations",
                    "value": default_tolerations
                    + [toleration.to_dict() for toleration in server.server_options.tolerations],
                }
            ],
        }
    ]


def session_affinity(server: UserServer) -> list[dict[str, Any]]:
    """Patch for session affinities.

    The static affinities from the configuration are ignored
    if the affinities are set in the server options (coming from CRC).
    """
    if not server.server_options.node_affinities:
        return [
            {
                "type": "application/json-patch+json",
                "patch": [
                    {
                        "op": "add",
                        "path": "/statefulset/spec/template/spec/affinity",
                        "value": server.config.sessions.affinity,
                    }
                ],
            }
        ]
    default_preferred_selector_terms: list[dict[str, Any]] = server.config.sessions.affinity.get(
        "nodeAffinity", {}
    ).get("preferredDuringSchedulingIgnoredDuringExecution", [])
    default_required_selector_terms: list[dict[str, Any]] = (
        server.config.sessions.affinity.get("nodeAffinity", {})
        .get("requiredDuringSchedulingIgnoredDuringExecution", {})
        .get("nodeSelectorTerms", [])
    )
    preferred_match_expressions: list[dict[str, str]] = []
    required_match_expressions: list[dict[str, str]] = []
    for affinity in server.server_options.node_affinities:
        if affinity.required_during_scheduling:
            required_match_expressions.append(affinity.json_match_expression())
        else:
            preferred_match_expressions.append(affinity.json_match_expression())
    return [
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/affinity",
                    "value": {
                        "nodeAffinity": {
                            "preferredDuringSchedulingIgnoredDuringExecution": default_preferred_selector_terms
                            + [
                                {
                                    "weight": 1,
                                    "preference": {
                                        "matchExpressions": preferred_match_expressions,
                                    },
                                }
                            ],
                            "requiredDuringSchedulingIgnoredDuringExecution": {
                                "nodeSelectorTerms": default_required_selector_terms
                                + [
                                    {
                                        "matchExpressions": required_match_expressions,
                                    }
                                ],
                            },
                        },
                    },
                }
            ],
        }
    ]


def session_node_selector(server: UserServer) -> list[dict[str, Any]]:
    """Patch for a node selector.

    If node affinities are specified in the server options
    (coming from CRC) node selectors in the static configuration are ignored.
    """
    if not server.server_options.node_affinities:
        return [
            {
                "type": "application/json-patch+json",
                "patch": [
                    {
                        "op": "add",
                        "path": "/statefulset/spec/template/spec/nodeSelector",
                        "value": server.config.sessions.node_selector,
                    }
                ],
            }
        ]
    return []


def priority_class(server: UserServer) -> list[dict[str, Any]]:
    """Set the priority class for the session, used to enforce resource quotas."""
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


def test(server: UserServer) -> list[dict[str, Any]]:
    """Test the server patches.

    RFC 6901 patches support test statements that will cause the whole patch
    to fail if the test statements are not correct. This is used to ensure that the
    order of containers in the amalthea manifests is what the notebook service expects.
    """
    patches = []
    # NOTE: Only the first 1 or 2 containers come "included" from Amalthea, the rest are patched
    # in. This test checks whether the expected number and order is received from Amalthea and
    # does not use all containers.
    container_names = (
        server.config.sessions.containers.registered[:2]
        if server.user.is_authenticated
        else server.config.sessions.containers.anonymous[:1]
    )
    for container_ind, container_name in enumerate(container_names):
        patches.append(
            {
                "type": "application/json-patch+json",
                "patch": [
                    {
                        "op": "test",
                        "path": (f"/statefulset/spec/template/spec/containers/{container_ind}/name"),
                        "value": container_name,
                    }
                ],
            }
        )
    return patches


def oidc_unverified_email(server: UserServer) -> list[dict[str, Any]]:
    """Allow users whose email is unverified in Keycloak to still be able to access their sessions."""
    patches = []
    if server.user.is_authenticated:
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
                            "value": str(server.config.sessions.oidc.allow_unverified_email).lower(),
                        },
                    },
                ],
            }
        )
    return patches


def dev_shm(server: UserServer) -> list[dict[str, Any]]:
    """Patches the /dev/shm folder used by some ML libraries for passing data between different processes."""
    return [
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/volumes/-",
                    "value": {
                        "name": "shm",
                        "emptyDir": {
                            "medium": "Memory",
                            # NOTE: We are giving /dev/shm up to half of the memory request
                            "sizeLimit": int(server.server_options.memory / 2)
                            if isinstance(server.server_options.memory, Number)
                            else "1Gi",
                        },
                    },
                },
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/0/volumeMounts/-",
                    "value": {
                        "mountPath": "/dev/shm",  # nosec B108
                        "name": "shm",
                    },
                },
            ],
        }
    ]
