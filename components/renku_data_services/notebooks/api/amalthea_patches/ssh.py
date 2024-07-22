"""Patches for enabling SSH access to a session."""

from typing import Any

from renku_data_services.notebooks.config import _NotebooksConfig


def main(config: _NotebooksConfig) -> list[dict[str, Any]]:
    """Adds the required configuration to the session statefulset for SSH access."""
    if not config.sessions.ssh.enabled:
        return []
    patches = [
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/service/spec/ports/-",
                    "value": {
                        "name": "ssh",
                        "port": config.sessions.ssh.service_port,
                        "protocol": "TCP",
                        "targetPort": "ssh",
                    },
                },
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/0/ports",
                    "value": [
                        {
                            "name": "ssh",
                            "containerPort": config.sessions.ssh.container_port,
                            "protocol": "TCP",
                        },
                    ],
                },
            ],
        }
    ]
    if config.sessions.ssh.host_key_secret:
        patches.append(
            {
                "type": "application/json-patch+json",
                "patch": [
                    {
                        "op": "add",
                        "path": "/statefulset/spec/template/spec/containers/0/volumeMounts/-",
                        "value": {
                            "name": "ssh-host-keys",
                            "mountPath": config.sessions.ssh.host_key_location,
                        },
                    },
                    {
                        "op": "add",
                        "path": "/statefulset/spec/template/spec/volumes/-",
                        "value": {
                            "name": "ssh-host-keys",
                            "secret": {"secretName": config.sessions.ssh.host_key_secret},
                        },
                    },
                ],
            }
        )
    return patches
