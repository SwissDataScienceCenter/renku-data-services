"""Patches for injecting custom certificates in session containers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from renku_data_services.notebooks.api.amalthea_patches.utils import get_certificates_volume_mounts

if TYPE_CHECKING:
    # NOTE: If these are directly imported then you get circular imports.
    from renku_data_services.notebooks.api.classes.server import UserServer


def proxy(server: UserServer) -> list[dict[str, Any]]:
    """Injects custom certificates volumes in the oauth2 proxy container."""
    etc_cert_volume_mounts = get_certificates_volume_mounts(
        server.config,
        custom_certs=False,
        etc_certs=True,
        read_only_etc_certs=True,
    )
    patches = [
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": ("/statefulset/spec/template/spec/containers/1/volumeMounts/-"),
                    "value": volume_mount,
                }
                for volume_mount in etc_cert_volume_mounts
            ],
        },
    ]
    if server.user.is_authenticated:
        patches.append(
            {
                "type": "application/json-patch+json",
                "patch": [
                    {
                        "op": "add",
                        "path": "/statefulset/spec/template/spec/containers/1/env/-",
                        "value": {
                            "name": "OAUTH2_PROXY_PROVIDER_CA_FILES",
                            "value": ",".join(
                                [
                                    (Path(volume_mount["mountPath"]) / "ca-certificates.crt").as_posix()
                                    for volume_mount in etc_cert_volume_mounts
                                ]
                            ),
                        },
                    },
                ],
            },
        )
    return patches
