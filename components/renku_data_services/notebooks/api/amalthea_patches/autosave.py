def main():
    patches = []
    patches.append(
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/0/lifecycle",
                    "value": {
                        "preStop": {
                            "exec": {
                                "command": [
                                    "/bin/sh",
                                    "-c",
                                    "/usr/local/bin/pre-stop.sh",
                                    "||",
                                    "true",
                                ]
                            }
                        }
                    },
                }
            ],
        }
    )
    patches.append(
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/volumes/-",
                    "value": {
                        "name": "notebook-helper-scripts-volume",
                        "configMap": {
                            "name": "notebook-helper-scripts",
                            "defaultMode": 493,
                        },
                    },
                }
            ],
        }
    )
    patches.append(
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/0/volumeMounts/-",
                    "value": {
                        "mountPath": "/usr/local/bin/pre-stop.sh",
                        "name": "notebook-helper-scripts-volume",
                        "subPath": "pre-stop.sh",
                    },
                }
            ],
        }
    )
    return patches
