"""Gitlab API."""
from dataclasses import dataclass, field
from typing import List

import httpx

from renku_data_services.base_models import APIUser, GitlabAccessLevel
from renku_data_services.errors import errors
from renku_data_services.utils.core import get_ssl_context


@dataclass(kw_only=True)
class GitlabAPI:
    """Adapter for interacting with the gitlab API."""

    gitlab_url: str
    gitlab_graphql_url: str = field(init=False)

    def __post_init__(self):
        """Sets the graphql url for gitlab."""
        gitlab_url = self.gitlab_url

        if not gitlab_url.startswith("http") and "://" not in gitlab_url:
            raise errors.ConfigurationError(message=f"Gitlab URL should start with 'http(s)://', got: {gitlab_url}")

        gitlab_url = gitlab_url.rstrip("/")

        self.gitlab_graphql_url = f"{gitlab_url}/api/graphql"

    async def filter_projects_by_access_level(
        self, user: APIUser, project_ids: List[str], min_access_level: GitlabAccessLevel
    ) -> List[str]:
        """Filter projects this user can access in gitlab with at least access level."""

        if not user.access_token or not user.name:
            return []
        header = {"Authorization": f"Bearer {user.access_token}", "Content-Type": "application/json"}
        ids = ",".join(f'"gid://gitlab/Project/{id}"' for id in project_ids)
        query_body = f"""
                    pageInfo {{
                      hasNextPage
                    }}
                    nodes {{
                        id
                        projectMembers(search: "{user.name}") {{
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
            async with httpx.AsyncClient(verify=get_ssl_context()) as client:
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
                            if n["user"]["id"].rsplit("/", maxsplit=1)[-1] == user.id
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
class DummyGitlabAPI:
    """Dummy gitlab API where the user with name John Doe has admin access to project 123456 and member access to 999999."""

    _store = {
        "John Doe": {
            GitlabAccessLevel.MEMBER: ["999999", "123456"],
            GitlabAccessLevel.ADMIN: ["123456"],
        },
    }

    async def filter_projects_by_access_level(
        self, user: APIUser, project_ids: List[str], min_access_level: GitlabAccessLevel
    ) -> List[str]:
        """Filter projects this user can access in gitlab with at least access level."""
        if not user.access_token or not user.name:
            return []
        if min_access_level == GitlabAccessLevel.PUBLIC:
            return []
        user_projects = self._store.get(user.name, {}).get(min_access_level, [])
        return [p for p in project_ids if p in user_projects]
