import pytest

# Public throwaway ed25519 key, no personal comment (same vector as test_core.py).
VALID_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPXhsNCQyI4HlAkaUIujCoGv3isiGoDR/MpS2yKlMfPY"
MISSING_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


@pytest.fixture
def valid_key() -> str:
    return VALID_KEY


async def test_ssh_key_crud(sanic_client, user_headers, valid_key):
    payload = {"public_key": valid_key, "name": "laptop"}
    _, response = await sanic_client.post("/api/data/user/ssh_keys", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    key = response.json
    assert key["name"] == "laptop"

    _, response = await sanic_client.get("/api/data/user/ssh_keys", headers=user_headers)
    assert response.status_code == 200
    assert [k["id"] for k in response.json] == [key["id"]]

    _, response = await sanic_client.get(f"/api/data/user/ssh_keys/{key['id']}", headers=user_headers)
    assert response.status_code == 200

    _, response = await sanic_client.delete(f"/api/data/user/ssh_keys/{key['id']}", headers=user_headers)
    assert response.status_code == 204

    _, response = await sanic_client.get("/api/data/user/ssh_keys", headers=user_headers)
    assert response.json == []


async def test_ssh_key_duplicate_is_conflict(sanic_client, user_headers, valid_key):
    payload = {"public_key": valid_key}
    _, response = await sanic_client.post("/api/data/user/ssh_keys", headers=user_headers, json=payload)
    assert response.status_code == 201
    _, response = await sanic_client.post("/api/data/user/ssh_keys", headers=user_headers, json=payload)
    assert response.status_code == 409


async def test_ssh_key_missing_id(sanic_client, user_headers):
    _, response = await sanic_client.get(f"/api/data/user/ssh_keys/{MISSING_ID}", headers=user_headers)
    assert response.status_code == 404
    _, response = await sanic_client.delete(f"/api/data/user/ssh_keys/{MISSING_ID}", headers=user_headers)
    assert response.status_code == 204


async def test_ssh_key_rejects_bad_key(sanic_client, user_headers):
    _, response = await sanic_client.post("/api/data/user/ssh_keys", headers=user_headers, json={"public_key": "nope"})
    assert response.status_code == 422


async def test_ssh_key_rejects_overlong_name(sanic_client, user_headers, valid_key):
    _, response = await sanic_client.post(
        "/api/data/user/ssh_keys", headers=user_headers, json={"public_key": valid_key, "name": "x" * 257}
    )
    assert response.status_code == 422


async def test_ssh_key_requires_auth(sanic_client, valid_key):
    _, response = await sanic_client.get("/api/data/user/ssh_keys")
    assert response.status_code == 401


async def test_ssh_key_is_scoped_to_user(sanic_client, user_headers, admin_headers, valid_key):
    _, response = await sanic_client.post(
        "/api/data/user/ssh_keys", headers=user_headers, json={"public_key": valid_key}
    )
    key_id = response.json["id"]
    _, response = await sanic_client.get(f"/api/data/user/ssh_keys/{key_id}", headers=admin_headers)
    assert response.status_code == 404
