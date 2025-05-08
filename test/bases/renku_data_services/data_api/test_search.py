import pytest


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
async def test_name_over_description(create_project, create_group, search_reprovision, search_query) -> None:
    """Name field more weight than others."""
    await create_project("bike project z", visibility="public", description="hello world")
    await create_project("project hoar z", visibility="public", description="hello bike bike world")
    await create_group("bike group")
    await search_reprovision()

    result = await search_query("bike")
    print("======")
    for e in result["items"]:
        print(f"{e["id"]}  {e["name"]}  {e["score"]}")
