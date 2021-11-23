from abc import ABC, abstractmethod
import escapism
from flask import current_app
from gitlab import Gitlab
from kubernetes import client
import re
import json
import base64
import jwt

from ...util.kubernetes_ import get_k8s_client
from .storage import AutosaveBranch


class User(ABC):
    @abstractmethod
    def get_autosaves(self, *args, **kwargs):
        pass

    def setup_k8s(self):
        self._k8s_client, self._k8s_namespace = get_k8s_client()
        self._k8s_api_instance = client.CustomObjectsApi(client.ApiClient())

    @property
    def jss(self):
        """Get a list of k8s jupyterserver objects for all the active servers of a user."""
        label_selector = (
            f"{current_app.config['RENKU_ANNOTATION_PREFIX']}"
            f"safe-username={self.safe_username}"
        )
        jss = self._k8s_api_instance.list_namespaced_custom_object(
            group=current_app.config["CRD_GROUP"],
            version=current_app.config["CRD_VERSION"],
            namespace=self._k8s_namespace,
            plural=current_app.config["CRD_PLURAL"],
            label_selector=label_selector,
        )
        return jss["items"]

    def get_renku_project(self, namespace_project):
        """Retrieve the GitLab project."""
        try:
            return self.gitlab_client.projects.get("{0}".format(namespace_project))
        except Exception as e:
            current_app.logger.warning(
                f"Cannot get project: {namespace_project} for user: {self.username}, error: {e}"
            )


class AnonymousUser(User):
    auth_header = "Renku-Auth-Anon-Id"

    def __init__(self, headers):
        if not current_app.config["ANONYMOUS_SESSIONS_ENABLED"]:
            raise ValueError(
                "Cannot use AnonymousUser when anonymous sessions are not enabled."
            )
        self.authenticated = self.auth_header in headers.keys()
        if not self.authenticated:
            return
        self.gitlab_client = Gitlab(current_app.config["GITLAB_URL"], api_version=4)
        self.username = headers[self.auth_header]
        self.safe_username = escapism.escape(self.username, escape_char="-").lower()
        self.full_name = None
        self.keycloak_user_id = None
        self.email = None
        self.oidc_issuer = None
        self.git_token = None
        self.setup_k8s()

    def get_autosaves(self, *args, **kwargs):
        return []


class RegisteredUser(User):
    auth_headers = [
        "Renku-Auth-Access-Token",
        "Renku-Auth-Id-Token",
        "Renku-Auth-Git-Credentials",
    ]

    def __init__(self, headers):
        self.authenticated = all(
            [header in headers.keys() for header in self.auth_headers]
        )
        if not self.authenticated:
            return
        parsed_id_token = self.parse_jwt_from_headers(headers)
        self.keycloak_user_id = parsed_id_token["sub"]
        self.email = parsed_id_token["email"]
        self.full_name = parsed_id_token["name"]
        self.username = parsed_id_token["preferred_username"]
        self.safe_username = escapism.escape(self.username, escape_char="-").lower()
        self.oidc_issuer = parsed_id_token["iss"]

        (
            self.git_url,
            self.git_auth_header,
            self.git_token,
        ) = self.git_creds_from_headers(headers)
        self.gitlab_client = Gitlab(
            self.git_url,
            api_version=4,
            oauth_token=self.git_token,
        )
        self.setup_k8s()

    @property
    def gitlab_user(self):
        try:
            return self.gitlab_client.user
        except AttributeError:
            self.gitlab_client.auth()
            return self.gitlab_client.user

    @staticmethod
    def parse_jwt_from_headers(headers):
        # No need to verify the signature because this is already done by the gateway
        return jwt.decode(headers["Renku-Auth-Id-Token"], verify=False)

    @staticmethod
    def git_creds_from_headers(headers):
        parsed_dict = json.loads(
            base64.decodebytes(headers["Renku-Auth-Git-Credentials"].encode())
        )
        git_url, git_credentials = next(iter(parsed_dict.items()))
        token_match = re.match(
            r"^[^\s]+\ ([^\s]+)$", git_credentials["AuthorizationHeader"]
        )
        git_token = token_match.group(1) if token_match is not None else None
        return git_url, git_credentials["AuthorizationHeader"], git_token

    def get_autosaves(self, namespace_project=None):
        """Get a list of autosaves for all projects for the user"""
        gl_project = (
            self.get_renku_project(namespace_project)
            if namespace_project is not None
            else None
        )
        autosaves = []
        # add any autosave branches, regardless of wheter pvcs are supported or not
        if namespace_project is None:  # get autosave branches from all projects
            projects = self.gitlab_client.projects.list()
        else:
            projects = [gl_project]
        for project in projects:
            for branch in project.branches.list():
                if (
                    re.match(r"^renku\/autosave\/" + self.username, branch.name)
                    is not None
                ):
                    autosave = AutosaveBranch.from_branch_name(
                        self, namespace_project, branch.name
                    )
                    if autosave is not None:
                        autosaves.append(autosave)
                    else:
                        current_app.logger.warning(
                            "Autosave branch {branch} for "
                            f"{namespace_project} cannot be instantiated."
                        )
        return autosaves
