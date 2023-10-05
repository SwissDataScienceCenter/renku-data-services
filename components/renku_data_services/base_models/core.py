"""Base models shared by services."""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Protocol

import httpx
from sanic import Request

from renku_data_services.errors import errors


class Authenticator(Protocol):
    """Interface for authenticating users."""

    token_field: str

    async def authenticate(self, access_token: str, request: Request) -> "APIUser":
        """Validates the user credentials (i.e. we can say that the user is a valid Renku user)."""
        ...


@dataclass(kw_only=True)
class APIUser:
    """The model for a user of the API, used for authentication."""

    is_admin: bool = False
    id: Optional[str] = None
    access_token: Optional[str] = field(repr=False, default=None)

    @property
    def is_authenticated(self):
        """Indicates whether the user has sucessfully logged in."""
        return self.id is not None


class GitlabAccessLevel(Enum):
    """Gitlab access level for filtering projects."""

    PUBLIC = 1
    """User isn't a member but project is public"""
    MEMBER = 2
    """User is a member of the project"""
    ADMIN = 3
    """A user with at least DEVELOPER priviledges in gitlab is considered an Admin"""


@dataclass(kw_only=True)
class GitlabAPIUser(APIUser):
    """The model for a user of the API for Gitlab authenticated requests."""

    name: str
    gitlab_url: str

    @property
    def gitlab_graphql_url(self):
        """Gets the graphql url for gitlab."""
        gitlab_url = self.gitlab_url

        if not gitlab_url.startswith("http") and "://" not in gitlab_url:
            gitlab_url = f"https://{gitlab_url}"

        gitlab_url = gitlab_url.rstrip("/")

        return f"{gitlab_url}/api/graphql"

    async def filter_projects_by_access_level(
        self, project_ids: List[str], min_access_level: GitlabAccessLevel
    ) -> List[str]:
        """Filter projects this user can access in gitlab with at least access level."""

        header = {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}
        ids = ",".join(f'"gid://gitlab/Project/{id}"' for id in project_ids)
        query_body = f"""
                    pageInfo {{
                      hasNextPage
                    }}
                    nodes {{
                        id
                        projectMembers(search: "{self.name}") {{
                            nodes {{
                                user {{
                                    id
                                    name
                                }}
                                accessLevel {{
                                    integerValue
                                }}
                            }}
                        }}
                    }}
        """
        body = {
            "query": f"""{{
                projects(ids: [{ids}]) {{
                    {query_body}
                }}
            }}
            """
        }

        async def _query_gitlab_graphql(body, header):
            async with httpx.AsyncClient() as client:
                resp = await client.post(self.gitlab_graphql_url, json=body, headers=header, timeout=10)
            if resp.status_code != 200:
                raise errors.BaseError(message=f"Error querying Gitlab api {self.gitlab_graphql_url}: {resp.text}")
            result = resp.json()

            if "data" not in result or "projects" not in result["data"]:
                raise errors.BaseError(message=f"Got unexpected response from Gitlab: {result}")
            return result

        resp_body = await _query_gitlab_graphql(body, header)
        result: List[str] = []

        def _process_projects(resp_body, min_access_level, result):
            for project in resp_body["data"]["projects"]["nodes"]:
                if min_access_level != GitlabAccessLevel.PUBLIC:
                    if not project["projectMembers"]["nodes"]:
                        continue
                    if min_access_level == GitlabAccessLevel.ADMIN:
                        max_level = max(
                            n["accessLevel"]["integerValue"]
                            for n in project["projectMembers"]["nodes"]
                            if n["user"]["id"].rsplit("/", maxsplit=1)[-1] == self.id
                        )
                        if max_level < 30:
                            continue
                result.append(project["id"].rsplit("/", maxsplit=1)[-1])

        _process_projects(resp_body, min_access_level, result)
        page_info = resp_body["data"]["projects"]["pageInfo"]
        while page_info["hasNextPage"]:
            cursor = page_info["endCursor"]
            body = {
                "query": f"""{{
                    projects(ids: [{ids}], after: "{cursor}") {{
                        {query_body}
                    }}
                }}
                """
            }
            resp_body = await _query_gitlab_graphql(body, header)
            page_info = resp_body["data"]["projects"]["pageInfo"]
            _process_projects(resp_body, min_access_level, result)

        return result


@dataclass(kw_only=True)
class DummyGitlabAPIUser(GitlabAPIUser):
    """Dummy user that has admin access to project 123456 and member access to 999999."""

    _admin_project_id = "123456"
    _member_project_id = "999999"

    async def filter_projects_by_access_level(
        self, project_ids: List[str], min_access_level: GitlabAccessLevel
    ) -> List[str]:
        """Filter projects this user can access in gitlab with at least access level."""
        if min_access_level == GitlabAccessLevel.PUBLIC:
            return project_ids
        if min_access_level == GitlabAccessLevel.MEMBER:
            return [p for p in project_ids if p in [self._admin_project_id, self._member_project_id]]
        return [p for p in project_ids if p == self._admin_project_id]


class UserStore(Protocol):
    """The interface through which Keycloak or a similar application can be accessed."""

    async def get_user_by_id(self, id: str, access_token: str) -> Optional["User"]:
        """Get a user by their unique Keycloak user ID."""
        ...


@dataclass(frozen=True, eq=True, kw_only=True)
class User:
    """User model."""

    keycloak_id: str
    id: Optional[int] = None

    @classmethod
    def from_dict(cls, data: dict) -> "User":
        """Create the model from a plain dictionary."""
        return cls(**data)
