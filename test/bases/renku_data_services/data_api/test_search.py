import pytest

from renku_data_services.base_models.core import APIUser
from renku_data_services.data_connectors.apispec import DataConnector as ApiDataConnector
from renku_data_services.namespace.apispec import GroupResponse as ApiGroup
from renku_data_services.project.apispec import Project as ApiProject
from renku_data_services.search.apispec import (
    Group as SearchGroup,
)
from renku_data_services.search.apispec import (
    SearchDataConnector,
    SearchEntity,
    SearchProject,
    SearchResult,
)
from renku_data_services.search.apispec import (
    User as SearchUser,
)
from renku_data_services.solr.entity_documents import EntityType
from renku_data_services.users.models import UserInfo
from test.bases.renku_data_services.data_api.conftest import (
    CreateDataConnectorCall,
    CreateGroupCall,
    CreateProjectCall,
    CreateUserCall,
    SearchQueryCall,
    SearchReprovisionCall,
)


# TODO: figure out how to run search tests fully parallel
@pytest.mark.xdist_group("search")
@pytest.mark.asyncio
async def test_direct_member_search(
    create_user: CreateUserCall,
    regular_user: UserInfo,
    search_reprovision: SearchReprovisionCall,
    create_project_model: CreateProjectCall,
    create_group_model: CreateGroupCall,
    search_query: SearchQueryCall,
) -> None:
    # - users: mads, wout, reg, florian
    # - group-lidl (owner=reg, editor=mads, viewer=wout)
    #   - project za (owner=mads, public, editor=florian)
    #   - project zb (owner=mads, private)
    #   - project zc (owner=mads, public, editor=wout)
    #
    # - group-visma (owner=reg, editor=wout, viewer=mads)
    #   - project ya (owner=wout, public)
    #   - project yb (owner=wout, private, viewer=florian)

    mads = await create_user(APIUser(id="mads-123", first_name="Mads", last_name="Pedersen"))
    wout = await create_user(APIUser(id="wout-567", first_name="Wout", last_name="van Art"))
    flor = await create_user(APIUser(id="flor-789", first_name="Florian", last_name="Lipowitz"))
    gr_lidl = await create_group_model(
        "Lidl-Trek",
        members=[{"id": mads.id, "role": "editor"}, {"id": wout.id, "role": "viewer"}],
        user=regular_user,
    )
    gr_visma = await create_group_model(
        "Visma LeaseABike",
        members=[{"id": wout.id, "role": "editor"}, {"id": mads.id, "role": "viewer"}],
        user=regular_user,
    )

    p1 = await create_project_model(
        "project za", mads, visibility="public", members=[{"id": flor.id, "role": "editor"}], namespace=gr_lidl.slug
    )
    p2 = await create_project_model("project zb", mads, visibility="private", namespace=gr_lidl.slug)
    p3 = await create_project_model(
        "project zc", mads, visibility="public", namespace=gr_lidl.slug, members=[{"id": wout.id, "role": "editor"}]
    )
    p4 = await create_project_model("project ya", wout, visibility="public", namespace=gr_visma.slug)
    p5 = await create_project_model(
        "Project yb", wout, visibility="private", members=[{"id": flor.id, "role": "viewer"}], namespace=gr_visma.slug
    )
    await search_reprovision()

    result = await search_query(f"namespace:{gr_lidl.slug}", user=flor)
    assert_search_result(result, [p1, p3])

    result = await search_query(f"namespace:{gr_lidl.slug}", user=wout)
    assert_search_result(result, [p1, p2, p3])

    result = await search_query(f"namespace:{gr_lidl.slug} direct_member:@{flor.namespace.path.first}", user=mads)
    assert_search_result(result, [p1])

    result = await search_query(f"namespace:{gr_lidl.slug} direct_member:@{wout.namespace.path.first}", user=mads)
    assert_search_result(result, [p3])

    result = await search_query(f"namespace:{gr_visma.slug} direct_member:@{flor.namespace.path.first}", user=wout)
    assert_search_result(result, [p5])

    result = await search_query(f"namespace:{gr_visma.slug} direct_member:@{flor.namespace.path.first}", user=mads)
    assert_search_result(result, [p5])

    result = await search_query(f"direct_member:@{wout.namespace.path.first}", user=regular_user)
    assert_search_result(result, [gr_lidl, gr_visma, p3, p4, p5])

    result = await search_query(f"direct_member:@{wout.namespace.path.first},@{mads.namespace.path.first}", user=mads)
    assert_search_result(result, [p3, gr_visma, gr_lidl])

    result = await search_query(f"inherited_member:@{wout.namespace.path.first}", user=regular_user)
    assert_search_result(result, [gr_lidl, gr_visma, p1, p2, p3, p4, p5])


# TODO: figure out how to run search tests fully parallel
@pytest.mark.xdist_group("search")
@pytest.mark.asyncio
async def test_inherited_member_search(
    create_user: CreateUserCall,
    regular_user: UserInfo,
    search_reprovision: SearchReprovisionCall,
    create_project_model: CreateProjectCall,
    create_group_model: CreateGroupCall,
    search_query: SearchQueryCall,
) -> None:
    mads = await create_user(APIUser(id="id-123", first_name="Mads", last_name="Pedersen"))
    wout = await create_user(APIUser(id="id-567", first_name="Wout", last_name="van Art"))

    gr_visma = await create_group_model("Visma", members=[{"id": wout.id, "role": "editor"}])
    gr_lidl = await create_group_model("Lidl-Trek", members=[{"id": mads.id, "role": "viewer"}])

    p1 = await create_project_model(name="private bike clean course 1 of 54", namespace=gr_visma.slug)
    p2 = await create_project_model(
        name="public bike clean course 42 of 54", namespace=gr_visma.slug, visibility="public"
    )
    p3 = await create_project_model(name="private get the bike dirty course 1/2", namespace=gr_lidl.slug)
    p4 = await create_project_model(
        name="public get the bike dirty course 2/2", namespace=gr_lidl.slug, visibility="public"
    )
    p5 = await create_project_model(name="public get the bike dirty course 2/2", visibility="private")

    await search_reprovision()

    ## Searching as 'regular_user' returns all entities, since this is the user implicitely used to create everything
    result = await search_query(f"inherited_member:@{regular_user.namespace.path.first}", regular_user)

    # 5 projects, 2 groups. users are removed there is no "membership" relation
    assert_search_result(result, [p1, p2, p3, p4, p5, gr_visma, gr_lidl], check_order=False)

    ## Searching as 'regular_user' peeking into a different users' entities
    result = await search_query(f"inherited_member:@{mads.namespace.path.first}", regular_user)
    assert_search_result(result, [p3, p4, gr_lidl], check_order=False)

    ## searching as mads, shows own enities
    result = await search_query(f"inherited_member:@{mads.namespace.path.first}", mads)
    assert_search_result(result, [p3, p4, gr_lidl], check_order=False)

    ## searching as wout, shows own enities
    result = await search_query(f"inherited_member:@{wout.namespace.path.first}", wout)
    assert_search_result(result, [p1, p2, gr_visma], check_order=False)

    ## mads inspecting wouts, shows only public entities from wout
    result = await search_query(f"inherited_member:@{wout.namespace.path.first}", mads)
    assert_search_result(result, [p2, gr_visma], check_order=False)

    ## searching as anonymous
    result = await search_query(f"inherited_member:@{wout.namespace.path.first}")
    assert_search_result(result, [p2, gr_visma], check_order=False)

    ## with the username, anonymous can find every entity the user is "member of"
    result = await search_query(f"inherited_member:@{regular_user.namespace.path.first}")
    assert_search_result(result, [p2, p4, gr_visma, gr_lidl], check_order=False)


# TODO: figure out how to run search tests fully parallel
@pytest.mark.xdist_group("search")
@pytest.mark.asyncio
async def test_projects(
    search_reprovision: SearchReprovisionCall, create_project_model: CreateProjectCall, search_query: SearchQueryCall
) -> None:
    """More occurrences of a word should push results up."""
    p1 = await create_project_model("Project Bike Z", visibility="public", description="a bike with a bike")

    p2 = await create_project_model("Project Bike A", visibility="public")
    p3 = await create_project_model("Project Bike R", visibility="public", description="a bike")
    await search_reprovision()

    result = await search_query("bike")
    assert_search_result(result, [p1, p3, p2], check_order=True)


# TODO: figure out how to run search tests fully parallel
@pytest.mark.xdist_group("search")
@pytest.mark.asyncio
async def test_distance(
    search_reprovision: SearchReprovisionCall, create_project_model: CreateProjectCall, search_query: SearchQueryCall
) -> None:
    """Search should be lenient to simple typos, distance=2."""
    p1 = await create_project_model("Project Bike Z", visibility="public", description="a bike with a bike")
    await search_reprovision()

    result = await search_query("mikin type:project")
    assert result.items == []

    result = await search_query("mike type:project")
    assert result.items is not None
    assert len(result.items) == 1
    assert __entity_id(result.items[0]) == p1.id


# TODO: figure out how to run search tests fully parallel
@pytest.mark.xdist_group("search")
@pytest.mark.asyncio
async def test_search_by_entity_type(
    create_project_model: CreateProjectCall,
    create_group_model: CreateGroupCall,
    create_data_connector_model: CreateDataConnectorCall,
    regular_user: UserInfo,
    search_query: SearchQueryCall,
    search_reprovision: SearchReprovisionCall,
) -> None:
    p1 = await create_project_model("Project Mine")
    g1 = await create_group_model("Group Wine")
    d1 = await create_data_connector_model("Data Zine", visibility="public")
    await search_reprovision()

    result = await search_query("type:dataconnector,project,group", regular_user)
    assert_search_result(result, [p1, g1, d1], check_order=False)

    for field in EntityType._member_map_.values():
        qstr = [f"type:{field.value}", f"type:{field.value.upper()}", f"type:{field.value.lower()}"]
        for q in qstr:
            result = await search_query(q, regular_user)
            items = result.items or []
            assert len(items) >= 1, f"Invalid results for query '{q}': {items}"
            for item in items:
                assert item.root.type == field.value


def __entity_id(e: SearchEntity) -> str:
    match e.root:
        case SearchProject() as p:
            return p.id

        case SearchGroup() as g:
            return g.id

        case SearchDataConnector() as d:
            return d.id

        case SearchUser() as u:
            return u.id


def __api_entity_id(e: ApiProject | ApiGroup | ApiDataConnector) -> str:
    match e:
        case ApiProject() as p:
            return p.id
        case ApiGroup() as g:
            return g.id
        case ApiDataConnector() as d:
            return d.id


def assert_search_result(
    result: SearchResult, entities: list[ApiProject | ApiGroup | ApiDataConnector], check_order: bool = False
) -> None:
    items = [__entity_id(e) for e in result.items or []]
    expected = [__api_entity_id(e) for e in entities]
    if not check_order:
        items.sort()
        expected.sort()

    if len(items) < len(expected):
        missing = set(expected).difference(set(items))
        raise Exception(f"Some entities are missing in the search result: {missing}")

    if len(items) > len(expected):
        missing = set(items).difference(set(expected))
        raise Exception(f"Too many results than expected: {missing}")

    for r, e in zip(items, expected, strict=True):
        assert r == e, f"Unexpected element (result={r}, expected={e}) in {items} vs {expected}"
