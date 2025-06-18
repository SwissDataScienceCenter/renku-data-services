import json
from typing import cast

import pytest

from renku_data_services.base_models.core import APIUser
from renku_data_services.project.apispec import Project as ApiProject
from renku_data_services.search.apispec import Group as SearchGroup
from renku_data_services.search.apispec import SearchProject, SearchResult
from renku_data_services.solr.entity_documents import EntityType
from renku_data_services.users.db import UserRepo
from renku_data_services.users.models import UserInfo


@pytest.mark.asyncio
async def test_member_search(
    app_manager_instance, regular_user, search_reprovision, create_project, create_group, search_query, admin_headers
) -> None:
    user_repo: UserRepo = app_manager_instance.kc_user_repo
    mads: UserInfo = cast(
        UserInfo,
        await user_repo.get_or_create_user(APIUser(id="id-123", first_name="Mads", last_name="Pedersen"), "id-123"),
    )
    wout: UserInfo = cast(
        UserInfo,
        await user_repo.get_or_create_user(APIUser(id="id-567", first_name="Wout", last_name="van Art"), "id-567"),
    )
    assert mads is not None and wout is not None

    gr_visma: dict = await create_group("Visma", members=[{"id": wout.id, "role": "editor"}])
    gr_lidl: dict = await create_group("Lidl-Trek", members=[{"id": mads.id, "role": "viewer"}])

    p1 = ApiProject.model_validate(
        await create_project(name="private bike clean course 1 of 54", namespace=gr_visma["slug"])
    )
    p2 = ApiProject.model_validate(
        await create_project(name="public bike clean course 42 of 54", namespace=gr_visma["slug"], visibility="public")
    )
    p3 = ApiProject.model_validate(
        await create_project(name="private get the bike dirty course 1/2", namespace=gr_lidl["slug"])
    )
    p4 = ApiProject.model_validate(
        await create_project(
            name="public get the bike dirty course 2/2", namespace=gr_lidl["slug"], visibility="public"
        )
    )
    p5 = ApiProject.model_validate(
        await create_project(name="public get the bike dirty course 2/2", visibility="private")
    )
    await search_reprovision()

    ## Searching as 'regular_user' returns all entities, since this is teh user implicitely used to create everything
    result = SearchResult.model_validate(
        await search_query(f"member:@{regular_user.namespace.path.first}", headers=__make_headers(regular_user))
    )
    # 5 projects, 2 groups. users are removed there is no "membership" relation
    assert_search_result(result, projects=[p1, p2, p3, p4, p5], groups=[gr_visma, gr_lidl])

    ## Searching as 'regular_user' peeking into a different users' entities
    result = SearchResult.model_validate(
        await search_query(f"member:@{mads.namespace.path.first}", headers=__make_headers(regular_user))
    )
    assert_search_result(result, projects=[p3, p4], groups=[gr_lidl])

    ## searching as mads, shows own enities
    result = SearchResult.model_validate(
        await search_query(f"member:@{mads.namespace.path.first}", headers=__make_headers(mads))
    )
    assert_search_result(result, projects=[p3, p4], groups=[gr_lidl])

    ## searching as wout, shows own enities
    result = SearchResult.model_validate(
        await search_query(f"member:@{wout.namespace.path.first}", headers=__make_headers(wout))
    )
    assert_search_result(result, projects=[p1, p2], groups=[gr_visma])

    ## mads inspecting wouts, shows only public entities from wout
    result = SearchResult.model_validate(
        await search_query(f"member:@{wout.namespace.path.first}", headers=__make_headers(mads))
    )
    assert_search_result(result, projects=[p2], groups=[gr_visma])

    ## searching as anonymous
    result = SearchResult.model_validate(await search_query(f"member:@{wout.namespace.path.first}"))
    assert_search_result(result, projects=[p2], groups=[gr_visma])

    ## with the username, anonymous can find every entity the user is "member of"
    result = SearchResult.model_validate(await search_query(f"member:@{regular_user.namespace.path.first}"))
    assert_search_result(result, projects=[p2, p4], groups=[gr_visma, gr_lidl])


@pytest.mark.asyncio
async def test_projects(search_reprovision, create_project, search_query) -> None:
    """More occurrences of a word should push results up."""
    await create_project("Project Bike Z", visibility="public", description="a bike with a bike")
    await create_project("Project Bike A", visibility="public")
    await create_project("Project Bike R", visibility="public", description="a bike")
    await search_reprovision()

    result = await search_query("bike")
    items = [e["name"] for e in result["items"]]
    assert items == ["Project Bike Z", "Project Bike R", "Project Bike A"]


@pytest.mark.asyncio
async def test_distance(search_reprovision, create_project, search_query) -> None:
    """Search should be lenient to simple typos, distance=2."""
    await create_project("Project Bike Z", visibility="public", description="a bike with a bike")
    await search_reprovision()

    result = await search_query("mikin type:project")
    assert result["items"] == []

    result = await search_query("mike type:project")
    assert len(result["items"]) == 1
    assert result["items"][0]["name"] == "Project Bike Z"


@pytest.mark.asyncio
async def test_search_by_entity_type(
    create_project, create_group, create_data_connector, user_headers, search_query, search_reprovision
) -> None:
    await create_project("Project Mine")
    await create_group("Group Wine")
    await create_data_connector("Data Zine", visibility="public")
    await search_reprovision()

    result = await search_query("", headers=user_headers)
    items = result["items"]
    types = set([e["type"] for e in items])
    assert types == set(["Project", "Group", "User", "DataConnector"])

    for field in EntityType._member_map_.values():
        qstr = [f"type:{field.value}", f"type:{field.value.upper()}", f"type:{field.value.lower()}"]
        for q in qstr:
            result = await search_query(q, headers=user_headers)
            items = result["items"]
            assert len(items) >= 1, f"Invalid results for query '{q}': {items}"
            for item in items:
                assert item["type"] == field.value


def __make_headers(user: UserInfo, admin: bool = False) -> dict[str, str]:
    access_token = json.dumps(
        {
            "is_admin": admin,
            "id": user.id,
            "name": f"{user.first_name} {user.last_name}",
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "full_name": f"{user.first_name} {user.last_name}",
        }
    )
    return {"Authorization": f"Bearer {access_token}"}


def assert_search_result(result: SearchResult, projects: list[ApiProject], groups: list) -> None:
    project_ids = set([p.id for p in projects])
    group_ids = set([g["id"] for g in groups])
    for item in result.items or []:
        match item.root:
            case SearchProject() as p:
                assert p.id in project_ids, f"Expected project {p.id} in the results {result}"
                project_ids.remove(p.id)
            case SearchGroup() as g:
                assert g.id in group_ids, f"Expected group {g.id} in the results {result}"
                group_ids.remove(g.id)
            case _:
                pass
    assert project_ids == set(), f"Some projects not found in the result: {project_ids}"
    assert group_ids == set(), f"Some groups not found in the result: {group_ids}"
