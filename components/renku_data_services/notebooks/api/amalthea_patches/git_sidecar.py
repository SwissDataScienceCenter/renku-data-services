import os
from flask import current_app

from ..classes.user import RegisteredUser


def main(server):
    # NOTE: Autosaves can be created only for registered users
    lifecycle = (
        {
            "preStop": {
                "exec": {
                    "command": [
                        "poetry",
                        "run",
                        "python",
                        "-m",
                        "git_services.sidecar.run_command",
                        "autosave",
                    ]
                }
            }
        }
        if type(server._user) is RegisteredUser
        else {}
    )
    patches = [
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/-",
                    "value": {
                        "image": current_app.config["GIT_RPC_SERVER_IMAGE"],
                        "name": "git-sidecar",
                        # Do not expose this until access control is in place
                        # "ports": [
                        #     {
                        #         "containerPort": 4000,
                        #         "name": "git-port",
                        #         "protocol": "TCP",
                        #     }
                        # ],
                        "env": [
                            {
                                "name": "MOUNT_PATH",
                                "value": f"/work/{server.gl_project.path}",
                            },
                            {
                                "name": "GIT_RPC_SENTRY__ENABLED",
                                "value": os.environ.get("SIDECAR_SENTRY_ENABLED"),
                            },
                            {
                                "name": "GIT_RPC_SENTRY__DSN",
                                "value": os.environ.get("SIDECAR_SENTRY_DSN"),
                            },
                            {
                                "name": "GIT_RPC_SENTRY__ENVIRONMENT",
                                "value": os.environ.get("SIDECAR_SENTRY_ENV"),
                            },
                            {
                                "name": "GIT_RPC_SENTRY__SAMPLE_RATE",
                                "value": os.environ.get("SIDECAR_SENTRY_SAMPLE_RATE"),
                            },
                            {
                                "name": "SENTRY_RELEASE",
                                "value": os.environ.get("SENTRY_RELEASE"),
                            },
                            {
                                "name": "CI_COMMIT_SHA",
                                "value": f"{server.commit_sha}",
                            },
                            {
                                "name": "RENKU_USERNAME",
                                "value": f"{server._user.username}",
                            },
                            # NOTE: The git proxy health port is also used to signal that the proxy
                            # can safely shut down after any autosave branches have been properly
                            # created.
                            {
                                "name": "GIT_PROXY_HEALTH_PORT",
                                "value": current_app.config["GIT_PROXY_HEALTH_PORT"],
                            },
                            {
                                "name": "AUTOSAVE_MINIMUM_LFS_FILE_SIZE_BYTES",
                                "value": str(
                                    current_app.config[
                                        "AUTOSAVE_MINIMUM_LFS_FILE_SIZE_BYTES"
                                    ]
                                ),
                            },
                        ],
                        # NOTE: Autosave Branch creation
                        "lifecycle": lifecycle,
                        "resources": {},
                        "securityContext": {
                            "allowPrivilegeEscalation": False,
                            "fsGroup": 100,
                            "runAsGroup": 1000,
                            "runAsUser": 1000,
                        },
                        "volumeMounts": [
                            {
                                "mountPath": f"/work/{server.gl_project.path}/",
                                "name": "workspace",
                                "subPath": f"{server.gl_project.path}/",
                            }
                        ],
                        # Enable readiness and liveness only when control is in place
                        # "livenessProbe": {
                        #     "httpGet": {"port": 4000, "path": "/"},
                        #     "periodSeconds": 30,
                        #     # delay should equal periodSeconds x failureThreshold
                        #     # from readiness probe values
                        #     "initialDelaySeconds": 600,
                        # },
                        # the readiness probe will retry 36 times over 360 seconds to see
                        # if the pod is ready to accept traffic - this gives the user session
                        # a maximum of 360 seconds to setup the git sidecar and clone the repo
                        # "readinessProbe": {
                        #     "httpGet": {"port": 4000, "path": "/"},
                        #     "periodSeconds": 10,
                        #     "failureThreshold": 60,
                        # },
                    },
                }
            ],
        }
    ]
    # We can add this to expose the git side-car once it's protected.
    # patches.append(
    #     {
    #         "type": "application/json-patch+json",
    #         "patch": [
    #             {
    #                 "op": "add",
    #                 "path": "/service/spec/ports/-",
    #                 "value": {
    #                     "name": "git-service",
    #                     "port": 4000,
    #                     "protocol": "TCP",
    #                     "targetPort": 4000,
    #                 },
    #             }
    #         ],
    #     }
    # )
    return patches
