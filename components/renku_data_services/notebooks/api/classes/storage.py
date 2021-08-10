from datetime import datetime
from flask import current_app
from gitlab.exceptions import GitlabGetError
from kubernetes import client
from kubernetes.client.models.v1_resource_requirements import V1ResourceRequirements
import requests
import re
from urllib.parse import urlparse

from ...util.kubernetes_ import get_k8s_client, make_pvc_name
from ...util.file_size import parse_file_size


class Autosave:
    def __init__(self, user, namespace_project, root_branch_name, root_commit_sha):
        self.user = user
        self.namespace_project = namespace_project
        self.namespace = "/".join(self.namespace_project.split("/")[:-1])
        self.project = self.namespace_project.split("/")[-1]
        self.gl_project = self.user.get_renku_project(self.namespace_project)
        self.root_branch_name = root_branch_name
        self.root_commit_sha = root_commit_sha
        self.validated = False
        self.valid = False
        self.validation_messages = []

    def _root_commit_is_parent_of(self, commit_sha):
        self.validate()
        if self.valid:
            res = requests.get(
                headers={"Authorization": f"Bearer {self.user.oauth_token}"},
                url=f"{current_app.config['GITLAB_URL']}/api/v4/"
                f"projects/{self.gl_project.id}/repository/merge_base",
                params={"refs[]": [self.root_commit_sha, commit_sha]},
            )
            if res.status_code == 200 and res.json().get("id") == self.root_commit_sha:
                return True
        return False

    def validate(self, force_rerun=False):
        if self.validated and not force_rerun:
            return
        validation_messages = []
        if self.gl_project is None:
            validation_messages.append(
                f"Project {self.namespace_project} does not exist."
            )
        try:
            root_commit_sha = self.gl_project.commits.get(self.root_commit_sha).id
            if len(self.root_commit_sha) < 40:
                self.root_commit_sha = root_commit_sha
        except GitlabGetError:
            validation_messages.append(
                "Root commit sha {root_commit_sha} does not exist."
            )
        if hasattr(self, "final_commit_sha"):
            try:
                final_commit_sha = self.gl_project.commits.get(self.final_commit_sha).id
                if len(self.final_commit_sha) < 40:
                    self.final_commit_sha = final_commit_sha
            except GitlabGetError:
                validation_messages.append(
                    "Final commit sha {root_commit_sha} does not exist."
                )
        self.gl_root_branch = self.gl_project.branches.get(self.root_branch_name)
        if self.gl_root_branch is None:
            validation_messages.append(
                f"Branch {self.root_branch_name} for project "
                f"{self.namespace_project} does not exist."
            )
        self.validated = True
        if len(validation_messages) == 0:
            self.valid = True
        else:
            current_app.logger.warning(
                "Validation for autosave branch/pvc "
                f"failed because: {validation_messages.join(', ')}"
            )
        self.validation_messages = validation_messages

    def cleanup(self, session_commit_sha):
        if self._root_commit_is_parent_of(session_commit_sha):
            if (type(self) is SessionPVC and not self.is_mounted) or type(
                self
            ) is AutosaveBranch:
                self.delete()

    @classmethod
    def from_name(cls, user, namespace_project, autosave_name):
        if re.match(AutosaveBranch.branch_name_regex, autosave_name) is not None:
            return AutosaveBranch.from_branch_name(
                user, namespace_project, autosave_name
            )
        else:
            return SessionPVC.from_pvc_name(user, autosave_name)


class AutosaveBranch(Autosave):
    branch_name_regex = (
        r"^renku/autosave/(?P<username>[^/]+)/(?P<root_branch_name>.+)/"
        r"(?P<root_commit_sha>[a-zA-Z0-9]{7})/(?P<final_commit_sha>[a-zA-Z0-9]{7})$"
    )

    def __init__(
        self,
        user,
        namespace_project,
        root_branch_name,
        root_commit_sha,
        final_commit_sha,
    ):
        super().__init__(user, namespace_project, root_branch_name, root_commit_sha)
        self.final_commit_sha = final_commit_sha
        self.name = (
            f"renku/autosave/{self.user.hub_username}/{root_branch_name}/"
            f"{root_commit_sha[:7]}/{final_commit_sha[:7]}"
        )
        self.creation_date = (
            None
            if not self.exists
            else datetime.fromisoformat(
                self.gl_project.branches.get(self.name).commit["committed_date"]
            )
        )

    @property
    def exists(self):
        return self.branch is not None

    def delete(self):
        if self.exists:
            self.gl_project.branches.delete(self.name)

    @property
    def branch(self):
        try:
            return self.gl_project.branches.get(self.name)
        except Exception:
            current_app.logger.warning(f"Cannot find branch {self.name}.")

    @classmethod
    def from_branch_name(cls, user, namespace_project, autosave_branch_name):
        match_res = re.match(cls.branch_name_regex, autosave_branch_name)
        if match_res is None:
            current_app.logger.warning(
                f"Invalid branch name {autosave_branch_name} for autosave branch."
            )
            return None
        return cls(
            user,
            namespace_project,
            match_res.group("root_branch_name"),
            match_res.group("root_commit_sha"),
            match_res.group("final_commit_sha"),
        )


class SessionPVC(Autosave):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        k8s_client, k8s_namespace = get_k8s_client()
        self.k8s_client = k8s_client
        self.k8s_namespace = k8s_namespace
        self.name = make_pvc_name(
            self.user.safe_username,
            self.namespace,
            self.project,
            self.root_branch_name,
            self.root_commit_sha,
        )
        self.creation_date = (
            None if not self.exists else self.pvc.metadata.creation_timestamp
        )

    @property
    def exists(self):
        return self.pvc is not None

    def delete(self):
        if self.exists:
            self.k8s_client.delete_namespaced_persistent_volume_claim(
                name=self.name, namespace=self.k8s_namespace
            )

    def create(self, storage_size, storage_class):
        self.validate()
        if not self.valid:
            raise ValueError(
                "Cannot create PVC because of invalid or missing parameters."
            )
        # check if we already have this PVC
        pvc = self.pvc
        if pvc is not None:
            # if the requested size is bigger than the original PVC, resize
            if parse_file_size(
                pvc.spec.resources.requests.get("storage")
            ) < parse_file_size(storage_size):
                pvc.spec.resources.requests["storage"] = storage_size
                self.k8s_client.patch_namespaced_persistent_volume_claim(
                    name=self.name,
                    namespace=self.k8s_namespace,
                    body=pvc,
                )
        else:
            git_host = urlparse(current_app.config.get("GITLAB_URL")).netloc
            pvc = client.V1PersistentVolumeClaim(
                metadata=client.V1ObjectMeta(
                    name=self.name,
                    annotations={
                        current_app.config.get("RENKU_ANNOTATION_PREFIX")
                        + "git-host": git_host,
                        current_app.config.get("RENKU_ANNOTATION_PREFIX")
                        + "namespace": self.namespace,
                        current_app.config.get("RENKU_ANNOTATION_PREFIX")
                        + "username": self.user.safe_username,
                        current_app.config.get("RENKU_ANNOTATION_PREFIX")
                        + "commit-sha": self.root_commit_sha,
                        current_app.config.get("RENKU_ANNOTATION_PREFIX")
                        + "branch": self.root_branch_name,
                        current_app.config.get("RENKU_ANNOTATION_PREFIX")
                        + "projectName": self.project,
                    },
                    labels={
                        "component": "singleuser-server",
                        current_app.config.get("RENKU_ANNOTATION_PREFIX")
                        + "username": self.user.safe_username,
                        current_app.config.get("RENKU_ANNOTATION_PREFIX")
                        + "commit-sha": self.root_commit_sha,
                        current_app.config.get("RENKU_ANNOTATION_PREFIX")
                        + "gitlabProjectId": str(self.gl_project.id),
                    },
                ),
                spec=client.V1PersistentVolumeClaimSpec(
                    access_modes=["ReadWriteOnce"],
                    volume_mode="Filesystem",
                    storage_class_name=storage_class,
                    resources=V1ResourceRequirements(
                        requests={"storage": storage_size}
                    ),
                ),
            )
            self.k8s_client.create_namespaced_persistent_volume_claim(
                self.k8s_namespace, pvc
            )

    @property
    def pvc(self):
        for pvc in self.user._get_pvcs():
            if pvc.metadata.name == self.name:
                return pvc
        return None

    @property
    def is_mounted(self):
        for pod in self.user.pods:
            for volume in pod.spec.volumes:
                pvc = volume.persistent_volume_claim
                if pvc is not None and pvc.claim_name == self.name:
                    return True
        return False

    @classmethod
    def from_pvc_name(cls, user, pvc_name):
        k8s_client, k8s_namespace = get_k8s_client()
        pvc = k8s_client.read_namespaced_persistent_volume_claim(
            pvc_name, k8s_namespace
        )
        return cls.from_pvc(user, pvc)

    @classmethod
    def from_pvc(cls, user, pvc):
        namespace = pvc.metadata.annotations.get(
            current_app.config.get("RENKU_ANNOTATION_PREFIX") + "namespace"
        )
        project = pvc.metadata.annotations.get(
            current_app.config.get("RENKU_ANNOTATION_PREFIX") + "projectName"
        )
        root_branch_name = pvc.metadata.annotations.get(
            current_app.config.get("RENKU_ANNOTATION_PREFIX") + "branch"
        )
        root_commit_sha = pvc.metadata.annotations.get(
            current_app.config.get("RENKU_ANNOTATION_PREFIX") + "commit-sha"
        )
        parameters_missing = [
            namespace is None,
            project is None,
            root_branch_name is None,
            root_commit_sha is None,
        ]
        if any(parameters_missing):
            current_app.logger.warning(
                "Required PVC annotations for creating SessionPVC are missing."
            )
            return None
        return cls(user, f"{namespace}/{project}", root_branch_name, root_commit_sha)
