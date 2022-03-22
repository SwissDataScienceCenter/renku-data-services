from flask import current_app
from kubernetes import client
import os

from ..classes.user import RegisteredUser
from .utils import get_certificates_volume_mounts


def git_clone(server):
    etc_cert_volume_mount = get_certificates_volume_mounts(
        custom_certs=False,
        etc_certs=True,
        read_only_etc_certs=True,
    )
    env = [
        {
            "name": "GIT_CLONE_MOUNT_PATH",
            "value": f"/work/{server.gl_project.path}",
        },
        {
            "name": "GIT_CLONE_REPOSITORY_URL",
            "value": server.gl_project.http_url_to_repo,
        },
        {
            "name": "GIT_CLONE_LFS_AUTO_FETCH",
            "value": "1" if server.server_options["lfs_auto_fetch"] else "0",
        },
        {"name": "GIT_CLONE_COMMIT_SHA", "value": server.commit_sha},
        {"name": "GIT_CLONE_BRANCH", "value": server.branch},
        {
            # used only for naming autosave branch
            "name": "GIT_CLONE_USER__USERNAME",
            "value": server._user.username,
        },
        {
            "name": "GIT_CLONE_GIT_AUTOSAVE",
            "value": "1" if server.autosave_allowed else "0",
        },
        {
            "name": "GIT_CLONE_GIT_URL",
            "value": server._user.gitlab_client._base_url,
        },
        {
            "name": "GIT_CLONE_USER__OAUTH_TOKEN",
            "value": server._user.git_token,
        },
        {
            "name": "GIT_CLONE_SENTRY__ENABLED",
            "value": os.environ.get("GIT_CLONE_SENTRY_ENABLED"),
        },
        {
            "name": "GIT_CLONE_SENTRY__DSN",
            "value": os.environ.get("GIT_CLONE_SENTRY_DSN"),
        },
        {
            "name": "GIT_CLONE_SENTRY__ENVIRONMENT",
            "value": os.environ.get("GIT_CLONE_SENTRY_ENV"),
        },
        {
            "name": "GIT_CLONE_SENTRY__SAMPLE_RATE",
            "value": os.environ.get("GIT_CLONE_SENTRY_SAMPLE_RATE"),
        },
        {
            "name": "SENTRY_RELEASE",
            "value": os.environ.get("SENTRY_RELEASE"),
        },
    ]
    if type(server._user) is RegisteredUser:
        env += [
            {
                "name": "GIT_CLONE_USER__EMAIL",
                "value": server._user.gitlab_user.email,
            },
            {
                "name": "GIT_CLONE_USER__FULL_NAME",
                "value": server._user.gitlab_user.name,
            },
        ]
    return [
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/initContainers/-",
                    "value": {
                        "image": current_app.config["GIT_CLONE_IMAGE"],
                        "name": "git-clone",
                        "resources": {},
                        "securityContext": {
                            "allowPrivilegeEscalation": False,
                            "fsGroup": 100,
                            "runAsGroup": 100,
                            "runAsUser": 1000,
                        },
                        "volumeMounts": [
                            {
                                "mountPath": "/work",
                                "name": "workspace",
                            },
                            *etc_cert_volume_mount,
                        ],
                        "env": env,
                    },
                },
            ],
        }
    ]


def certificates():
    initContainer = client.V1Container(
        name="init-certificates",
        image=current_app.config["CERTIFICATES_IMAGE"],
        volume_mounts=get_certificates_volume_mounts(
            etc_certs=True,
            custom_certs=True,
            read_only_etc_certs=False,
        ),
    )
    volume_etc_certs = client.V1Volume(
        name="etc-ssl-certs", empty_dir=client.V1EmptyDirVolumeSource(medium="Memory")
    )
    volume_custom_certs = client.V1Volume(
        name="custom-ca-certs",
        projected=client.V1ProjectedVolumeSource(
            default_mode=440,
            sources=[
                {"secret": {"name": i.get("secret")}}
                for i in current_app.config["CUSTOM_CA_CERTS_SECRETS"]
                if i is not None and i.get("secret") is not None
            ],
        ),
    )
    api_client = client.ApiClient()
    patches = [
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/initContainers/-",
                    "value": api_client.sanitize_for_serialization(initContainer),
                },
            ],
        },
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/volumes/-",
                    "value": api_client.sanitize_for_serialization(volume_etc_certs),
                },
            ],
        },
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/volumes/-",
                    "value": api_client.sanitize_for_serialization(volume_custom_certs),
                },
            ],
        },
    ]
    return patches
