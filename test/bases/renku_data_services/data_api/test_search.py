import pytest
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.base_models.core import APIUser
from renku_data_services.data_connectors.apispec import DataConnector as ApiDataConnector
from renku_data_services.namespace.apispec import GroupResponse as ApiGroup
from renku_data_services.project.apispec import Project as ApiProject
from renku_data_services.search.apispec import (
    SearchDataConnector,
    SearchEntity,
    SearchGroup,
    SearchProject,
    SearchResult,
    SearchUser,
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
from test.utils import TestDependencyManager


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
    sanic_client_with_solr: SanicASGITestClient,
    app_manager_instance: TestDependencyManager,
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

    mads = await create_user(app_manager_instance, APIUser(id="mads-123", first_name="Mads", last_name="Pedersen"))
    print(mads)
    wout = await create_user(app_manager_instance, APIUser(id="wout-567", first_name="Wout", last_name="van Art"))
    flor = await create_user(app_manager_instance, APIUser(id="flor-789", first_name="Florian", last_name="Lipowitz"))
    gr_lidl = await create_group_model(
        sanic_client_with_solr,
        "Lidl-Trek",
        members=[{"id": mads.id, "role": "editor"}, {"id": wout.id, "role": "viewer"}],
        user=regular_user,
    )
    print(gr_lidl)
    gr_visma = await create_group_model(
        sanic_client_with_solr,
        "Visma LeaseABike",
        members=[{"id": wout.id, "role": "editor"}, {"id": mads.id, "role": "viewer"}],
        user=regular_user,
    )

    p1 = await create_project_model(
        sanic_client_with_solr,
        "project za",
        mads,
        visibility="public",
        members=[{"id": flor.id, "role": "editor"}],
        namespace=gr_lidl.slug,
    )
    p2 = await create_project_model(
        sanic_client_with_solr, "project zb", mads, visibility="private", namespace=gr_lidl.slug
    )
    p3 = await create_project_model(
        sanic_client_with_solr,
        "project zc",
        mads,
        visibility="public",
        namespace=gr_lidl.slug,
        members=[{"id": wout.id, "role": "editor"}],
    )
    p4 = await create_project_model(
        sanic_client_with_solr, "project ya", wout, visibility="public", namespace=gr_visma.slug
    )
    p5 = await create_project_model(
        sanic_client_with_solr,
        "Project yb",
        wout,
        visibility="private",
        members=[{"id": flor.id, "role": "viewer"}],
        namespace=gr_visma.slug,
    )
    await search_reprovision(app_manager_instance)

    result = await search_query(sanic_client_with_solr, f"namespace:{gr_lidl.slug}", user=flor)
    assert_search_result(result, [p1, p3])

    result = await search_query(sanic_client_with_solr, f"namespace:{gr_lidl.slug}", user=wout)
    assert_search_result(result, [p1, p2, p3])

    result = await search_query(
        sanic_client_with_solr, f"namespace:{gr_lidl.slug} direct_member:@{flor.namespace.path.first}", user=mads
    )
    assert_search_result(result, [p1])

    result = await search_query(
        sanic_client_with_solr, f"namespace:{gr_lidl.slug} direct_member:@{wout.namespace.path.first}", user=mads
    )
    assert_search_result(result, [p3])

    result = await search_query(
        sanic_client_with_solr, f"namespace:{gr_visma.slug} direct_member:@{flor.namespace.path.first}", user=wout
    )
    assert_search_result(result, [p5])

    result = await search_query(
        sanic_client_with_solr, f"namespace:{gr_visma.slug} direct_member:@{flor.namespace.path.first}", user=mads
    )
    assert_search_result(result, [p5])

    result = await search_query(
        sanic_client_with_solr, f"direct_member:@{wout.namespace.path.first}", user=regular_user
    )
    assert_search_result(result, [gr_lidl, gr_visma, p3, p4, p5])
    print(result)

    result = await search_query(
        sanic_client_with_solr, f"direct_member:@{wout.namespace.path.first},@{mads.namespace.path.first}", user=mads
    )
    assert_search_result(result, [p3, gr_visma, gr_lidl])

    result = await search_query(
        sanic_client_with_solr, f"inherited_member:@{wout.namespace.path.first}", user=regular_user
    )
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
    sanic_client_with_solr: SanicASGITestClient,
    app_manager_instance: TestDependencyManager,
) -> None:
    mads = await create_user(app_manager_instance, APIUser(id="id-123", first_name="Mads", last_name="Pedersen"))
    wout = await create_user(app_manager_instance, APIUser(id="id-567", first_name="Wout", last_name="van Art"))

    gr_visma = await create_group_model(sanic_client_with_solr, "Visma", members=[{"id": wout.id, "role": "editor"}])
    gr_lidl = await create_group_model(sanic_client_with_solr, "Lidl-Trek", members=[{"id": mads.id, "role": "viewer"}])

    p1 = await create_project_model(
        sanic_client_with_solr, name="private bike clean course 1 of 54", namespace=gr_visma.slug
    )
    p2 = await create_project_model(
        sanic_client_with_solr, name="public bike clean course 42 of 54", namespace=gr_visma.slug, visibility="public"
    )
    p3 = await create_project_model(
        sanic_client_with_solr, name="private get the bike dirty course 1/2", namespace=gr_lidl.slug
    )
    p4 = await create_project_model(
        sanic_client_with_solr, name="public get the bike dirty course 2/2", namespace=gr_lidl.slug, visibility="public"
    )
    p5 = await create_project_model(
        sanic_client_with_solr, name="public get the bike dirty course 2/2", visibility="private"
    )

    await search_reprovision(app_manager_instance)

    ## Searching as 'regular_user' returns all entities, since this is the user implicitly used to create everything
    result = await search_query(
        sanic_client_with_solr, f"inherited_member:@{regular_user.namespace.path.first}", regular_user
    )

    # 5 projects, 2 groups. users are removed there is no "membership" relation
    assert_search_result(result, [p1, p2, p3, p4, p5, gr_visma, gr_lidl], check_order=False)

    ## Searching as 'regular_user' peeking into a different users' entities
    result = await search_query(sanic_client_with_solr, f"inherited_member:@{mads.namespace.path.first}", regular_user)
    assert_search_result(result, [p3, p4, gr_lidl], check_order=False)

    ## searching as mads, shows own entities
    result = await search_query(sanic_client_with_solr, f"inherited_member:@{mads.namespace.path.first}", mads)
    assert_search_result(result, [p3, p4, gr_lidl], check_order=False)

    ## searching as wout, shows own entities
    result = await search_query(sanic_client_with_solr, f"inherited_member:@{wout.namespace.path.first}", wout)
    assert_search_result(result, [p1, p2, gr_visma], check_order=False)

    ## mads inspecting wout, shows only public entities from wout
    result = await search_query(sanic_client_with_solr, f"inherited_member:@{wout.namespace.path.first}", mads)
    assert_search_result(result, [p2, gr_visma], check_order=False)

    ## searching as anonymous
    result = await search_query(sanic_client_with_solr, f"inherited_member:@{wout.namespace.path.first}")
    assert_search_result(result, [p2, gr_visma], check_order=False)

    ## with the username, anonymous can find every entity the user is "member of"
    result = await search_query(sanic_client_with_solr, f"inherited_member:@{regular_user.namespace.path.first}")
    assert_search_result(result, [p2, p4, gr_visma, gr_lidl], check_order=False)


# TODO: figure out how to run search tests fully parallel
@pytest.mark.xdist_group("search")
@pytest.mark.asyncio
async def test_projects(
    search_reprovision: SearchReprovisionCall,
    create_project_model: CreateProjectCall,
    search_query: SearchQueryCall,
    sanic_client_with_solr: SanicASGITestClient,
    app_manager_instance: TestDependencyManager,
) -> None:
    """More occurrences of a word should push results up."""
    p1 = await create_project_model(
        sanic_client_with_solr, "Project Bike Z", visibility="public", description="a bike with a bike"
    )

    p2 = await create_project_model(sanic_client_with_solr, "Project Bike A", visibility="public")
    p3 = await create_project_model(sanic_client_with_solr, "Project Bike R", visibility="public", description="a bike")
    await search_reprovision(app_manager_instance)

    result = await search_query(sanic_client_with_solr, "bike")
    assert_search_result(result, [p1, p3, p2], check_order=True)


# TODO: figure out how to run search tests fully parallel
@pytest.mark.xdist_group("search")
@pytest.mark.asyncio
async def test_distance(
    search_reprovision: SearchReprovisionCall,
    create_project_model: CreateProjectCall,
    search_query: SearchQueryCall,
    sanic_client_with_solr: SanicASGITestClient,
    app_manager_instance: TestDependencyManager,
) -> None:
    """Search should be lenient to simple typos, distance=2."""
    p1 = await create_project_model(
        sanic_client_with_solr, "Project Bike Z", visibility="public", description="a bike with a bike"
    )
    await search_reprovision(app_manager_instance)

    result = await search_query(sanic_client_with_solr, "mikin type:project")
    assert result.items == []

    result = await search_query(sanic_client_with_solr, "mike type:project")
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
    sanic_client_with_solr: SanicASGITestClient,
    app_manager_instance: TestDependencyManager,
) -> None:
    p1 = await create_project_model(sanic_client_with_solr, "Project Mine")
    g1 = await create_group_model(sanic_client_with_solr, "Group Wine")
    d1 = await create_data_connector_model("Data Zine", visibility="public")
    await search_reprovision(app_manager_instance)

    result = await search_query(sanic_client_with_solr, "type:dataconnector,project,group", regular_user)
    assert_search_result(result, [p1, g1, d1], check_order=False)

    for field in EntityType._member_map_.values():
        qstr = [f"type:{field.value}", f"type:{field.value.upper()}", f"type:{field.value.lower()}"]
        for q in qstr:
            result = await search_query(sanic_client_with_solr, q, regular_user)
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


# TODO: figure out how to run search tests fully parallel
@pytest.mark.xdist_group("search")
@pytest.mark.asyncio
async def test_group_slug_change_updates_project_search(
    app_manager_instance,
    create_data_connector_model,
    create_group_model,
    create_project_model,
    regular_user,
    sanic_client_with_solr,
    search_push_updates,
    search_query,
    search_reprovision,
    user_headers,
) -> None:
    """Test that changing a group's slug updates the search index for resources in that group."""
    slug = "test-group"
    group = await create_group_model(sanic_client_with_solr, "Test Group", user=regular_user, slug=slug)
    project = await create_project_model(
        sanic_client_with_solr, "Project", user=regular_user, visibility="public", namespace=group.slug
    )
    data_connector = await create_data_connector_model("Data Connector", visibility="public", namespace=group.slug)
    await search_reprovision(app_manager_instance)

    # Resources are found in the old namespace
    resources = await search_query(
        sanic_client_with_solr, f"namespace:{group.slug} type:dataconnector,project", user=regular_user
    )
    assert_search_result(resources, [data_connector, project])

    new_slug = "renamed-test-group"

    _, response = await sanic_client_with_solr.patch(
        f"/api/data/groups/{group.slug}", headers=user_headers, json={"slug": new_slug}
    )
    assert response.status_code == 200, response.text
    assert response.json["slug"] == new_slug

    # Only push the update messages to Solr (not a full reprovision)
    await search_push_updates(app_manager_instance, clear_index=False)

    # Verify resources' namespace are updated
    resources = await search_query(
        sanic_client_with_solr, f"namespace:{new_slug} type:dataconnector,project", user=regular_user
    )
    assert_search_result(resources, [data_connector, project])

    # Verify resources aren't found in the old namespace anymore
    resources = await search_query(
        sanic_client_with_solr, f"namespace:{slug} type:dataconnector,project", user=regular_user
    )
    assert_search_result(resources, [])
