import escapism
from flask import request, current_app
import gitlab
from kubernetes import client
import re
import requests

from ...util.kubernetes_ import get_k8s_client


class User:
    def __init__(self):
        self._validate_app_config()
        self.hub_username = self._get_hub_username()
        self.safe_username = (
            escapism.escape(self.hub_username, escape_char="-").lower()
            if self.hub_username is not None
            else None
        )
        self.hub_user = self._get_hub_user()
        self.oauth_token = self._get_oauth_token()
        self.gitlab_client = gitlab.Gitlab(
            current_app.config.get("GITLAB_URL"),
            api_version=4,
            oauth_token=self.oauth_token,
        )

    def _validate_app_config(self):
        """Confirm that the app configuration contains the minimum required
        parameters needed for the handling users."""
        if (
            current_app.config.get("JUPYTERHUB_ADMIN_AUTH") is None
            or current_app.config.get("GITLAB_URL") is None
            or current_app.config.get("JUPYTERHUB_ADMIN_HEADERS") is None
        ):
            raise ValueError("Flask app configuration is insufficient for User object.")

    def _get_hub_username(self):
        """Get the jupyterhub username of the user."""
        token = (
            request.cookies.get(current_app.config["JUPYTERHUB_ADMIN_AUTH"].cookie_name)
            or request.headers.get("Authorization", "")[len("token") :].strip()
        )
        if token:
            _user = current_app.config["JUPYTERHUB_ADMIN_AUTH"].user_for_token(token)
            if _user:
                return _user["name"]
        else:
            return None

    def _get_hub_user(self):
        """Get information (i.e. username, email, etc) about the logged in user from Jupyterhub"""
        url = current_app.config["JUPYTERHUB_ADMIN_AUTH"].api_url
        response = requests.get(
            f"{url}/users/{self.hub_username}",
            headers=current_app.config["JUPYTERHUB_ADMIN_HEADERS"],
        )
        return response.json()

    def _get_oauth_token(self):
        """Retrieve the user's GitLab token from the oauth metadata."""
        auth_state = self.hub_user.get("auth_state", None)
        return None if not auth_state else auth_state.get("access_token")

    @property
    def pods(self):
        """Get a list of k8s pod objects for all the active servers of a user."""
        k8s_client, k8s_namespace = get_k8s_client()
        pods = k8s_client.list_namespaced_pod(
            k8s_namespace,
            label_selector=f"heritage=jupyterhub,renku.io/username={self.safe_username}",
        )
        return pods.items

    def get_autosaves(self, namespace_project=None):
        """Get a list of autosaves for all projects for the user"""
        autosaves = []
        # add pvcs to list of autosaves only if pvcs are supported in deployment
        if current_app.config["NOTEBOOKS_SESSION_PVS_ENABLED"]:
            if namespace_project is None:
                autosaves += self._get_pvcs()
            else:
                project_name_annotation_key = (
                    current_app.config.get("RENKU_ANNOTATION_PREFIX") + "projectName"
                )
                autosaves += [
                    pvc
                    for pvc in self._get_pvcs()
                    if pvc.metadata.annotations.get(project_name_annotation_key)
                    == namespace_project.split("/")[-1]
                ]
        # add any autosave branches, regardless of wheter pvcs are supported or not
        if namespace_project is None:  # get autosave branches from all projects
            projects = self.gitlab_client.projects.list()
        else:
            projects = [self.get_renku_project(namespace_project)]
        for project in projects:
            for branch in project.branches.list():
                if re.match(r"^renku\/autosave\/", branch.name) is not None:
                    autosaves.append(
                        {
                            "branch": branch,
                            "root_commit": project.commits.get(
                                branch.name.split("/")[-2]
                            ).id,
                        }
                    )
        return autosaves

    def _get_pvcs(self):
        """Get all session pvcs that belong to this user"""
        if not current_app.config["NOTEBOOKS_SESSION_PVS_ENABLED"]:
            return []
        else:
            k8s_client, k8s_namespace = get_k8s_client()
            label_selector = ",".join(
                [
                    "component=singleuser-server",
                    current_app.config.get("RENKU_ANNOTATION_PREFIX")
                    + "username="
                    + self.safe_username,
                ]
            )
            try:
                return k8s_client.list_namespaced_persistent_volume_claim(
                    k8s_namespace, label_selector=label_selector
                ).items
            except client.ApiException:
                return []

    def get_renku_project(self, namespace_project):
        """Retrieve the GitLab project."""
        try:
            return self.gitlab_client.projects.get("{0}".format(namespace_project))
        except Exception as e:
            current_app.logger.error(
                f"Cannot get project: {namespace_project} for user: {self.hub_username}, error: {e}"
            )
