"""Gitlab authenticator."""
from dataclasses import dataclass

import gitlab
from sanic import Request

import renku_data_services.base_models as base_models
from renku_data_services import errors


@dataclass
class GitlabAuthenticator:
    """Authenticator for gitlab repos.

    Note:
        Once we have a project service, this should get information on what type of git provider is used from there
        and support different backends.
    """

    gitlab_url: str

    async def authenticate(self, access_token: str, request: Request | None) -> base_models.APIUser:
        """Checks the validity of the access token."""

        project_id: str | None = None

        if request is not None:
            if "project_id" in request.json:
                project_id = request.json["project_id"]
            elif project_id in request.query_args:
                project_id = request.query_args["project_id"]
            elif "project_id" in request.args:
                project_id = request.args["project_id"]

        if project_id is not None:
            result = await self._auth_with_repo(access_token, project_id)
        else:
            raise errors.ValidationError(message="project_id not found")

        return result

    async def _auth_with_repo(self, access_token: str, project_id: str) -> base_models.APIUser:
        """Check if a user has access to a repository on gitlab."""
        client = gitlab.Gitlab(self.gitlab_url, oauth_token=access_token)
        user = client.user
        if user is None:
            raise errors.Unauthorized(message="User not authorized")

        if user.state != "active":
            raise errors.Unauthorized(message="User isn't active")

        user_id = user.get_id()

        if user_id is None:
            raise errors.Unauthorized(message="Could not get user id")

        project = client.projects.get(id=project_id)
        member = project.members.get(id=user_id)

        is_admin = False

        if member.access_level >= 30:
            # Developer, Maintainer and Owner
            is_admin = True

        return base_models.APIUser(is_admin, str(user_id), access_token)
