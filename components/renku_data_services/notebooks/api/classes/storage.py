import re
from datetime import datetime

import requests
from flask import current_app
from gitlab.exceptions import GitlabError

from ...config import config


class Autosave:
    def __init__(self, user, namespace_project, root_branch_name, root_commit_sha):
        self.user = user
        self.namespace_project = namespace_project
        self.namespace = "/".join(self.namespace_project.split("/")[:-1])
        self.project = self.namespace_project.split("/")[-1]
        self.gl_project = self.user.get_renku_project(self.namespace_project)
        self.root_branch_name = root_branch_name
        self.root_commit_sha = root_commit_sha

    def _root_commit_is_parent_of(self, commit_sha):
        if not self.gl_project:
            return False
        res = requests.get(
            headers={"Authorization": f"Bearer {self.user.git_token}"},
            url=f"{config.git.url}/api/v4/"
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

    def __str__(self):
        return (
            f"<Autosave user: {self.user} namespace: {self.namespace} project: "
            f"{self.project} root_branch: {self.root_branch_name} "
            f"root_commit: {self.root_commit_sha}>"
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
        try:
            self.creation_date = datetime.fromisoformat(
                self.gl_project.branches.get(self.name).commit["committed_date"]
            )
        except (GitlabError, AttributeError):
            self.creation_date = None

    def delete(self):
        try:
            self.gl_project.branches.delete(self.name)
        except GitlabError:
            pass
        else:
            return self.name

    @classmethod
    def from_branch_name(cls, user, namespace_project, autosave_branch_name):
        match_res = re.match(cls.branch_name_regex, autosave_branch_name)
        if match_res is None:
            current_app.logger.warning(
                f"Invalid branch name {autosave_branch_name} for autosave branch."
            )
            return None
        if match_res.group("username") != user.username:
            return None
        return cls(
            user,
            namespace_project,
            match_res.group("root_branch_name"),
            match_res.group("root_commit_sha"),
            match_res.group("final_commit_sha"),
        )

    def __str__(self):
        return (
            f"<Autosave user: {self.user} namespace: {self.namespace} project: "
            f"{self.project} root_branch: {self.root_branch_name} "
            f"root_commit: {self.root_commit_sha} final_commit: {self.final_commit_sha}>"
        )
