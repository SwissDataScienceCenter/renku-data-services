"""Notebooks user model definitions."""

from functools import lru_cache

from gitlab import Gitlab
from gitlab.v4.objects.projects import Project
from gitlab.v4.objects.users import CurrentUser

from renku_data_services.app_config import logging

logger = logging.getLogger(__name__)


class NotebooksGitlabClient:
    """Client for gitlab to be used only in the notebooks, will be eventually eliminated."""

    def __init__(self, url: str, gitlab_token: str | None = None):
        self.gitlab_client = Gitlab(url, api_version="4", oauth_token=gitlab_token, per_page=50)

    @property
    def gitlab_user(self) -> CurrentUser | None:
        """Get the Gitlab user."""
        if not getattr(self.gitlab_client, "user", None):
            self.gitlab_client.auth()
        return self.gitlab_client.user

    @lru_cache(maxsize=8)
    def get_renku_project(self, namespace_project: str) -> Project | None:
        """Retrieve the GitLab project."""
        try:
            return self.gitlab_client.projects.get(f"{namespace_project}")
        except Exception as e:
            logger.warning(f"Cannot find the gitlab project: {namespace_project}, error: {e}")
        return None
