from typing import Any, Dict, List
from ...config import config


def main() -> List[Dict[str, Any]]:
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
                            "secret": {
                                "secretName": config.sessions.ssh.host_key_secret
                            },
                        },
                    },
                ],
            }
        )
    return patches
