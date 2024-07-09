import pytest


@pytest.mark.asyncio
async def test_list_namespaces(sanic_client, user_headers) -> None:
    payload = {
        "name": "Group1",
        "slug": "group-1",
        "description": "Group 1 Description",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    _, response = await sanic_client.get("/api/data/namespaces", headers=user_headers)
    assert response.status_code == 200, response.text
    res_json = response.json
    assert len(res_json) == 2
    user_ns = res_json[0]
    assert user_ns["slug"] == "user.doe"
    group_ns = res_json[1]
    assert group_ns["slug"] == "group-1"


@pytest.mark.asyncio
async def test_list_namespaces_all_groups_are_public(sanic_client, user_headers, member_1_headers) -> None:
    payload = {
        "name": "Group 1",
        "slug": "group-1",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    payload = {
        "name": "Group 2",
        "slug": "group-2",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=member_1_headers, json=payload)
    assert response.status_code == 201, response.text

    _, response = await sanic_client.get("/api/data/namespaces", headers=user_headers)

    assert response.status_code == 200, response.text
    res_json = response.json
    assert len(res_json) == 3
    user_ns = res_json[0]
    assert user_ns["slug"] == "user.doe"
    group_1_ns = res_json[1]
    assert group_1_ns["slug"] == "group-1"
    group_2_ns = res_json[2]
    assert group_2_ns["slug"] == "group-2"


@pytest.mark.asyncio
async def test_list_namespaces_filter_minimum_role(sanic_client, user_headers, member_1_headers) -> None:
    payload = {
        "name": "Group 1",
        "slug": "group-1",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    payload = {
        "name": "Group 2",
        "slug": "group-2",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=member_1_headers, json=payload)
    assert response.status_code == 201, response.text
    payload = {
        "name": "Group 3",
        "slug": "group-3",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=member_1_headers, json=payload)
    assert response.status_code == 201, response.text
    payload = {
        "name": "Group 4",
        "slug": "group-4",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=member_1_headers, json=payload)
    assert response.status_code == 201, response.text
    new_members = [{"id": "user", "role": "viewer"}]
    _, response = await sanic_client.patch(
        "/api/data/groups/group-3/members", headers=member_1_headers, json=new_members
    )
    assert response.status_code == 200, response.text
    new_members = [{"id": "user", "role": "editor"}]
    _, response = await sanic_client.patch(
        "/api/data/groups/group-4/members", headers=member_1_headers, json=new_members
    )
    assert response.status_code == 200, response.text

    _, response = await sanic_client.get("/api/data/namespaces?minimum_role=viewer", headers=user_headers)

    assert response.status_code == 200, response.text
    res_json = response.json
    assert len(res_json) == 4
    user_ns = res_json[0]
    assert user_ns["slug"] == "user.doe"
    group_1_ns = res_json[1]
    assert group_1_ns["slug"] == "group-1"
    group_2_ns = res_json[2]
    assert group_2_ns["slug"] == "group-3"
    group_3_ns = res_json[3]
    assert group_3_ns["slug"] == "group-4"

    _, response = await sanic_client.get("/api/data/namespaces?minimum_role=editor", headers=user_headers)

    assert response.status_code == 200, response.text
    res_json = response.json
    assert len(res_json) == 3
    user_ns = res_json[0]
    assert user_ns["slug"] == "user.doe"
    group_1_ns = res_json[1]
    assert group_1_ns["slug"] == "group-1"
    group_2_ns = res_json[2]
    assert group_2_ns["slug"] == "group-4"

    _, response = await sanic_client.get("/api/data/namespaces?minimum_role=owner", headers=user_headers)

    assert response.status_code == 200, response.text
    res_json = response.json
    assert len(res_json) == 2
    user_ns = res_json[0]
    assert user_ns["slug"] == "user.doe"
    group_1_ns = res_json[1]
    assert group_1_ns["slug"] == "group-1"


@pytest.mark.asyncio
async def test_get_namespace_by_slug(sanic_client, user_headers) -> None:
    payload = {
        "name": "Group1",
        "slug": "group-1",
        "description": "Group 1 Description",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    _, response = await sanic_client.get(f"/api/data/namespaces/{payload['slug']}", headers=user_headers)
    assert response.status_code == 200, response.text
    assert response.json["slug"] == payload["slug"]
    assert response.json["namespace_kind"] == "group"
    _, response = await sanic_client.get("/api/data/namespaces/user.doe", headers=user_headers)
    assert response.status_code == 200, response.text
    assert response.json["slug"] == "user.doe"
    assert response.json["namespace_kind"] == "user"


@pytest.mark.asyncio
async def test_get_namespace_by_slug_anonymously(sanic_client, user_headers) -> None:
    payload = {
        "name": "Group1",
        "slug": "group-1",
        "description": "Group 1 Description",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text

    _, response = await sanic_client.get(f"/api/data/namespaces/{payload['slug']}")
    assert response.status_code == 200, response.text
    assert response.json["slug"] == payload["slug"]
    assert response.json["namespace_kind"] == "group"

    _, response = await sanic_client.get("/api/data/namespaces/user.doe")
    assert response.status_code == 200, response.text
    assert response.json["slug"] == "user.doe"
    assert response.json["namespace_kind"] == "user"
