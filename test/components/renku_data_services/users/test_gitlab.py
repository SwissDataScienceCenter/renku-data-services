from unittest.mock import MagicMock, patch

import httpx
import pytest

import renku_data_services.authn.gitlab as gitlab
import renku_data_services.errors as errors
from renku_data_services.git.gitlab import GitlabAPI


def mock_gl_api(
    has_user: bool = True,
    user_state: str = "active",
    project_exists: bool = True,
    is_member: bool = True,
    access_level: int = 30,
) -> MagicMock:
    gl_api = MagicMock()
    gl_api.return_value = gl_api
    if not has_user:
        gl_api.user.return_value = None
        return gl_api
    user = MagicMock()
    gl_api.user = user
    user.state = user_state
    user.id = "123456"
    project = MagicMock()
    if not project_exists:
        gl_api.projects.get.side_effect = gitlab.gitlab.GitlabGetError("Project not found")

    gl_api.projects.get.return_value = project

    if not is_member:
        project.members.get.side_effect = gitlab.gitlab.GitlabGetError("Member not found")
    member = MagicMock()
    project.members.get.return_value = member
    member.access_level = access_level
    return gl_api


def mock_request(json: bool = True) -> MagicMock:
    request = MagicMock()
    request.headers.get.return_value = "abcdefg"
    if json:
        request.json.__contains__.return_value = True
        request.json.__getitem__.return_value = {"project_id": "654321"}
    else:
        request.args.__contains__.return_value = True
        request.args.get.return_value = "654321"
    return request


@pytest.mark.asyncio
@pytest.mark.parametrize("json", [True, False])
async def test_gitlab_auth(json: bool, monkeypatch) -> None:
    gl_mock = mock_gl_api()
    with monkeypatch.context() as monkey:
        monkey.setattr(gitlab.gitlab, "Gitlab", gl_mock)
        gl_auth = gitlab.GitlabAuthenticator(gitlab_url="https://localhost")
        assert gl_auth.gitlab_url == "https://localhost"
        request = mock_request(json)

        result = await gl_auth.authenticate("xxxxxx", request)
        assert result


@pytest.mark.asyncio
async def test_gitlab_auth_no_user(monkeypatch) -> None:
    gl_mock = mock_gl_api(has_user=False)
    with monkeypatch.context() as monkey:
        monkey.setattr(gitlab.gitlab, "Gitlab", gl_mock)
        gl_auth = gitlab.GitlabAuthenticator(gitlab_url="https://localhost")
        assert gl_auth.gitlab_url == "https://localhost"
        request = mock_request()

        with pytest.raises(errors.ForbiddenError):
            await gl_auth.authenticate("xxxxxx", request)


@pytest.mark.asyncio
async def test_gitlab_auth_not_active(monkeypatch) -> None:
    gl_mock = mock_gl_api(user_state="inactive")
    with monkeypatch.context() as monkey:
        monkey.setattr(gitlab.gitlab, "Gitlab", gl_mock)
        gl_auth = gitlab.GitlabAuthenticator(gitlab_url="https://localhost")
        assert gl_auth.gitlab_url == "https://localhost"
        request = mock_request()

        with pytest.raises(errors.ForbiddenError):
            await gl_auth.authenticate("xxxxxx", request)


@pytest.mark.asyncio
@patch(
    "renku_data_services.git.gitlab.httpx.AsyncClient.post",
    return_value=httpx.Response(
        200,
        json={
            "data": {
                "projects": {
                    "pageInfo": {"hasNextPage": False, "endCursor": "eyJpZCI6IjkxNjM4In0"},
                    "nodes": [
                        {"id": "gid://gitlab/Project/1", "projectMembers": {"nodes": []}},
                        {
                            "id": "gid://gitlab/Project/2",
                            "projectMembers": {
                                "nodes": [
                                    {
                                        "user": {"id": "gid://gitlab/User/21", "name": "John Dow"},
                                        "accessLevel": {"stringValue": "OWNER", "integerValue": 50},
                                    }
                                ]
                            },
                        },
                        {
                            "id": "gid://gitlab/Project/3",
                            "projectMembers": {
                                "nodes": [
                                    {
                                        "user": {"id": "gid://gitlab/User/21", "name": "JohnDoe"},
                                        "accessLevel": {"stringValue": "OWNER", "integerValue": 20},
                                    }
                                ]
                            },
                        },
                    ],
                }
            }
        },
    ),
)
async def test_gitlab_user(monkeypatch) -> None:
    import renku_data_services.base_models as base_models

    gitlab_client = GitlabAPI(gitlab_url="https://gitlab.url.com")
    user = base_models.APIUser(is_admin=False, id="21", access_token="xxxxxx", full_name="John Doe")  # nosec: B106
    projects = await gitlab_client.filter_projects_by_access_level(
        user, ["1", "2", "3"], min_access_level=base_models.GitlabAccessLevel.PUBLIC
    )
    assert len(projects) == 3

    projects = await gitlab_client.filter_projects_by_access_level(
        user, ["1", "2", "3"], min_access_level=base_models.GitlabAccessLevel.MEMBER
    )
    assert len(projects) == 2

    projects = await gitlab_client.filter_projects_by_access_level(
        user, ["1", "2", "3"], min_access_level=base_models.GitlabAccessLevel.ADMIN
    )
    assert len(projects) == 1
