import pytest

from renku_data_services.solr.entity_documents import EntityType


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
