from datetime import datetime
from flask import current_app
from gitlab.exceptions import GitlabGetError
import requests
import re


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
                headers={"Authorization": f"Bearer {self.user.git_token}"},
                url=f"{current_app.config['GITLAB_URL']}/api/v4/"
                f"projects/{self.gl_project.id}/repository/merge_base",
                params={"refs[]": [self.root_commit_sha, commit_sha]},
            )
            if (
                res.status_code == 200
                and res.json().get("id") == self.root_commit_sha
                and self.root_commit_sha != commit_sha
            ):
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
            if type(self) is AutosaveBranch:
                self.delete()

    @classmethod
    def from_name(cls, user, namespace_project, autosave_name):
        if re.match(AutosaveBranch.branch_name_regex, autosave_name) is not None:
            return AutosaveBranch.from_branch_name(
                user, namespace_project, autosave_name
            )


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
            f"renku/autosave/{self.user.username}/{root_branch_name}/"
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
