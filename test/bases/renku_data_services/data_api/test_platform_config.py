"""Tests for platform config blueprints."""

import urllib.parse

import pytest
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.data_api.dependencies import DependencyManager
from test.bases.renku_data_services.data_api.utils import merge_headers

DUMMY_ULID = "01FZ8RSZ9KAKYQZ1ZZZZZZZZZZ"
DUMMY_ULID_2 = "11FZ8RSZ9KAKYQZ1ZZZZZZZZZZ"


@pytest.mark.asyncio
async def test_get_platform_config(app_manager: DependencyManager, sanic_client: SanicASGITestClient) -> None:
    _, res = await sanic_client.get("/api/data/platform/config")

    assert res.status_code == 200, res.text
    assert res.json is not None
    platform_config = res.json
    assert platform_config.get("incident_banner") == ""
    assert platform_config.get("etag") != ""


@pytest.mark.asyncio
async def test_patch_platform_config(sanic_client: SanicASGITestClient, admin_headers: dict[str, str]) -> None:
    _, res = await sanic_client.get("/api/data/platform/config")
    initial_config = res.json

    headers = merge_headers(admin_headers, {"If-Match": initial_config["etag"]})
    payload = {"incident_banner": "Some content"}

    _, res = await sanic_client.patch("/api/data/platform/config", headers=headers, json=payload)

    assert res.status_code == 200, res.text
    assert res.json is not None
    platform_config = res.json
    assert platform_config.get("incident_banner") == "Some content"
    assert platform_config.get("etag") != initial_config["etag"]


@pytest.mark.asyncio
async def test_patch_platform_config_unauthorized(
    sanic_client: SanicASGITestClient, user_headers: dict[str, str]
) -> None:
    _, res = await sanic_client.get("/api/data/platform/config")
    initial_config = res.json

    headers = merge_headers(user_headers, {"If-Match": initial_config["etag"]})
    payload = {"incident_banner": "Some content"}

    _, res = await sanic_client.patch("/api/data/platform/config", headers=headers, json=payload)

    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_delete_redirect(sanic_client: SanicASGITestClient, admin_headers: dict[str, str]) -> None:
    payload = {"source_url": "/projects/ns/project-slug", "target_url": f"/p/{DUMMY_ULID}"}
    _, res = await sanic_client.post("/api/data/platform/redirects", headers=admin_headers, json=payload)
    assert res.status_code == 201, f"status code {res.status_code} != 201"
    assert res.json is not None
    url_redirect_plan = res.json
    assert url_redirect_plan.get("source_url") == "/projects/ns/project-slug"
    assert url_redirect_plan.get("target_url") == f"/p/{DUMMY_ULID}"
    assert url_redirect_plan.get("etag") != ""

    encoded_url = urllib.parse.quote_plus("/projects/ns/project-slug")
    delete_headers = merge_headers(admin_headers, {"If-Match": url_redirect_plan["etag"]})
    _, res = await sanic_client.delete(f"/api/data/platform/redirects/{encoded_url}", headers=delete_headers)
    assert res.status_code == 204, f"status code {res.status_code} != 204"

    parameters = {"page": 1, "per_page": 5}
    _, res = await sanic_client.get("/api/data/platform/redirects", headers=admin_headers, params=parameters)

    assert res.status_code == 200, f"status code {res.status_code} != 200"
    assert res.json is not None
    assert res.headers["page"] == "1"
    assert res.headers["per-page"] == "5"
    assert res.headers["total"] == "0"
    assert res.headers["total-pages"] == "0"


@pytest.mark.asyncio
async def test_get_redirects(sanic_client: SanicASGITestClient, admin_headers: dict[str, str]) -> None:
    parameters = {"page": 1, "per_page": 5}
    headers = admin_headers
    _, res = await sanic_client.get("/api/data/platform/redirects", headers=headers, params=parameters)

    assert res.status_code == 200, f"status code {res.status_code} != 200"
    assert res.json is not None
    assert res.headers["page"] == "1"
    assert res.headers["per-page"] == "5"
    assert res.headers["total"] == "0"
    assert res.headers["total-pages"] == "0"


@pytest.mark.asyncio
async def test_get_redirect(sanic_client: SanicASGITestClient, admin_headers: dict[str, str]) -> None:
    url = "/projects/ns/project-slug"
    encoded_url = urllib.parse.quote_plus(url)
    _, res = await sanic_client.get(f"/api/data/platform/redirects/{encoded_url}")
    assert res.status_code == 404, res.text
    assert res.json is not None
    error_object = res.json
    assert (
        error_object.get("error").get("message")
        == f"A redirect for '{url}' does not exist or you do not have access to it."
    )
    # getting registered redirects is tested in test_post_redirect


@pytest.mark.asyncio
async def test_patch_redirect(sanic_client: SanicASGITestClient, admin_headers: dict[str, str]) -> None:
    payload = {"source_url": "/projects/ns/project-slug", "target_url": f"/p/{DUMMY_ULID}"}

    _, res = await sanic_client.post("/api/data/platform/redirects", headers=admin_headers, json=payload)
    assert res.status_code == 201, res.text
    assert res.json is not None
    url_redirect_plan = res.json
    assert url_redirect_plan.get("source_url") == "/projects/ns/project-slug"
    assert url_redirect_plan.get("target_url") == f"/p/{DUMMY_ULID}"
    assert url_redirect_plan.get("etag") != ""

    encoded_url = urllib.parse.quote_plus("/projects/ns/project-slug")
    _, res = await sanic_client.get(f"/api/data/platform/redirects/{encoded_url}")
    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json.get("source_url") == "/projects/ns/project-slug"
    assert res.json.get("target_url") == f"/p/{DUMMY_ULID}"
    assert res.json.get("etag") == url_redirect_plan.get("etag")

    patch_headers = merge_headers(admin_headers, {"If-Match": url_redirect_plan["etag"]})
    payload = {"target_url": f"/p/{DUMMY_ULID_2}"}
    _, res = await sanic_client.patch(
        f"/api/data/platform/redirects/{encoded_url}", headers=patch_headers, json=payload
    )
    assert res.status_code == 200, res.text
    assert res.json is not None
    updated_plan = res.json
    assert updated_plan.get("source_url") == "/projects/ns/project-slug"
    assert updated_plan.get("target_url") == f"/p/{DUMMY_ULID_2}"
    assert updated_plan.get("etag") != ""

    _, res = await sanic_client.get(f"/api/data/platform/redirects/{encoded_url}")
    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json.get("source_url") == "/projects/ns/project-slug"
    assert res.json.get("target_url") == f"/p/{DUMMY_ULID_2}"


@pytest.mark.asyncio
async def test_patch_redirect_non_existant(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
) -> None:
    payload = {"target_url": f"/p/{DUMMY_ULID}"}
    encoded_url = urllib.parse.quote_plus("/projects/ns/project-slug")
    patch_headers = merge_headers(admin_headers, {"If-Match": "some-etag"})
    _, res = await sanic_client.patch(
        f"/api/data/platform/redirects/{encoded_url}", headers=patch_headers, json=payload
    )
    # should not allow patching a redirect that does not exist
    assert res.status_code == 404, res.status_code
    assert res.json is not None
    assert (
        res.json.get("error").get("message") == "A redirect for source URL '/projects/ns/project-slug' does not exist."
    )


@pytest.mark.asyncio
async def test_patch_redirect_unauthorized(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], user_headers: dict[str, str]
) -> None:
    payload = {"target_url": f"/p/{DUMMY_ULID}"}
    encoded_url = urllib.parse.quote_plus("/projects/ns/project-slug")
    patch_headers = merge_headers(admin_headers, {"If-Match": "some-etag"})
    _, res = await sanic_client.patch(
        f"/api/data/platform/redirects/{encoded_url}", headers=patch_headers, json=payload
    )
    # should not allow patching a redirect that does not exist
    assert res.status_code == 404, res.status_code
    assert res.json is not None
    assert (
        res.json.get("error").get("message") == "A redirect for source URL '/projects/ns/project-slug' does not exist."
    )

    payload = {"source_url": "/projects/ns/project-slug", "target_url": f"/p/{DUMMY_ULID}"}
    _, res = await sanic_client.post("/api/data/platform/redirects", headers=admin_headers, json=payload)
    assert res.status_code == 201, f"status code {res.status_code} != 201"
    url_redirect_plan = res.json
    _, res = await sanic_client.get(f"/api/data/platform/redirects/{encoded_url}")
    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json.get("source_url") == "/projects/ns/project-slug"
    assert res.json.get("target_url") == f"/p/{DUMMY_ULID}"
    assert res.json.get("etag") == url_redirect_plan.get("etag")

    patch_headers = merge_headers(user_headers, {"If-Match": url_redirect_plan["etag"]})
    payload = {"target_url": "/p/ns2/project-slug2"}
    _, res = await sanic_client.patch(
        f"/api/data/platform/redirects/{encoded_url}", headers=patch_headers, json=payload
    )
    assert res.status_code == 403, res.status_code
    assert res.json is not None
    assert res.json.get("error").get("message") == "You do not have the required permissions for this operation."


@pytest.mark.asyncio
async def test_post_redirect(sanic_client: SanicASGITestClient, admin_headers: dict[str, str]) -> None:
    payload = {"source_url": "/projects/ns/project-slug", "target_url": f"/p/{DUMMY_ULID}"}
    _, res = await sanic_client.post("/api/data/platform/redirects", headers=admin_headers, json=payload)
    assert res.status_code == 201, f"status code {res.status_code} != 201"
    assert res.json is not None
    url_redirect_plan_1 = res.json
    assert url_redirect_plan_1.get("source_url") == "/projects/ns/project-slug"
    assert url_redirect_plan_1.get("target_url") == f"/p/{DUMMY_ULID}"
    assert url_redirect_plan_1.get("etag") != ""

    payload = {"source_url": "https://gitlab.renkulab.io/foo", "target_url": "https://github.com/foo"}
    _, res = await sanic_client.post("/api/data/platform/redirects", headers=admin_headers, json=payload)
    assert res.status_code == 201, f"status code {res.status_code} != 201"
    assert res.json is not None
    url_redirect_plan_2 = res.json
    assert url_redirect_plan_2.get("source_url") == "https://gitlab.renkulab.io/foo"
    assert url_redirect_plan_2.get("target_url") == "https://github.com/foo"
    assert url_redirect_plan_2.get("etag") != ""

    parameters = {"page": 1, "per_page": 5}
    _, res = await sanic_client.get("/api/data/platform/redirects", headers=admin_headers, params=parameters)

    assert res.status_code == 200, f"status code {res.status_code} != 200"
    assert res.json is not None
    assert res.headers["page"] == "1"
    assert res.headers["per-page"] == "5"
    assert res.headers["total"] == "2"
    assert res.headers["total-pages"] == "1"

    redirects = res.json
    assert redirects[0].get("etag") == url_redirect_plan_1.get("etag")

    encoded_url = urllib.parse.quote_plus("/projects/ns/project-slug")
    _, res = await sanic_client.get(f"/api/data/platform/redirects/{encoded_url}")
    assert res.status_code == 200, f"status code {res.status_code} != 200"
    assert res.json is not None
    assert res.json.get("source_url") == "/projects/ns/project-slug"
    assert res.json.get("target_url") == f"/p/{DUMMY_ULID}"


@pytest.mark.asyncio
async def test_post_redirect_input_validation(sanic_client: SanicASGITestClient, admin_headers: dict[str, str]) -> None:
    payload = {"source_url": "/foo/ns/project-slug", "target_url": "/p/ns/project-slug"}
    _, res = await sanic_client.post("/api/data/platform/redirects", headers=admin_headers, json=payload)
    assert res.status_code == 422, f"status code {res.status_code} != 422"
    assert res.json is not None
    assert res.json.get("error").get("message") == "The source URL must start with /projects/."

    payload = {"source_url": "/projects/ns/project-slug", "target_url": "/p/ns/project-slug"}
    _, res = await sanic_client.post("/api/data/platform/redirects", headers=admin_headers, json=payload)
    assert res.status_code == 422, f"status code {res.status_code} != 422"
    assert res.json is not None
    assert res.json.get("error").get("message") == "The target URL path must match the pattern /p/ULID."

    payload = {"source_url": "http://gitlab.renkulab.io/foo", "target_url": "http://github.com"}
    _, res = await sanic_client.post("/api/data/platform/redirects", headers=admin_headers, json=payload)
    assert res.status_code == 422, f"status code {res.status_code} != 422"
    assert res.json is not None
    assert res.json.get("error").get("message") == "The source URL must use HTTPS."

    payload = {"source_url": "https://foo.bar/foo", "target_url": "http://github.com"}
    _, res = await sanic_client.post("/api/data/platform/redirects", headers=admin_headers, json=payload)
    assert res.status_code == 422, f"status code {res.status_code} != 422"
    assert res.json is not None
    assert res.json.get("error").get("message") == "The source URL host must be gitlab.renkulab.io."

    payload = {"source_url": "https://gitlab.renkulab.io/foo//", "target_url": "http://github.com"}
    _, res = await sanic_client.post("/api/data/platform/redirects", headers=admin_headers, json=payload)
    assert res.status_code == 422, f"status code {res.status_code} != 422"
    assert res.json is not None
    assert res.json.get("error").get("message") == "The source URL path is not canonical."

    payload = {"source_url": "https://gitlab.renkulab.io/foo/../../", "target_url": "http://github.com"}
    _, res = await sanic_client.post("/api/data/platform/redirects", headers=admin_headers, json=payload)
    assert res.status_code == 422, f"status code {res.status_code} != 422"
    assert res.json is not None
    assert res.json.get("error").get("message") == "The source URL path is not canonical."

    payload = {"source_url": "https://gitlab.renkulab.io/foo", "target_url": "http://github.com/bar"}
    _, res = await sanic_client.post("/api/data/platform/redirects", headers=admin_headers, json=payload)
    assert res.status_code == 422, f"status code {res.status_code} != 422"
    assert res.json is not None
    assert res.json.get("error").get("message") == "The target URL must use HTTPS."

    payload = {"source_url": "https://gitlab.renkulab.io/foo", "target_url": "https://github.com/bar?query=1"}
    _, res = await sanic_client.post("/api/data/platform/redirects", headers=admin_headers, json=payload)
    assert res.status_code == 422, f"status code {res.status_code} != 422"
    assert res.json is not None
    assert res.json.get("error").get("message") == "The target URL must not include parameters, a query, or a fragment."

    payload = {"source_url": "https://gitlab.renkulab.io/foo", "target_url": "https://github.com/bar#fragment"}
    _, res = await sanic_client.post("/api/data/platform/redirects", headers=admin_headers, json=payload)
    assert res.status_code == 422, f"status code {res.status_code} != 422"
    assert res.json is not None
    assert res.json.get("error").get("message") == "The target URL must not include parameters, a query, or a fragment."


@pytest.mark.asyncio
async def test_post_redirect_duplicate(sanic_client: SanicASGITestClient, admin_headers: dict[str, str]) -> None:
    headers = admin_headers
    payload = {"source_url": "/projects/ns/project-slug", "target_url": f"/p/{DUMMY_ULID}"}

    _, res = await sanic_client.post("/api/data/platform/redirects", headers=headers, json=payload)
    assert res.status_code == 201, res.text
    assert res.json is not None
    url_redirect_plan = res.json
    assert url_redirect_plan.get("source_url") == "/projects/ns/project-slug"
    assert url_redirect_plan.get("target_url") == f"/p/{DUMMY_ULID}"
    assert url_redirect_plan.get("etag") != ""

    payload = {"source_url": "/projects/ns/project-slug", "target_url": f"/p/{DUMMY_ULID_2}"}
    _, res = await sanic_client.post("/api/data/platform/redirects", headers=headers, json=payload)
    assert res.status_code == 409, (res.status_code, res.text)
    assert res.json is not None
    url_redirect_plan = res.json
    assert url_redirect_plan.get("error").get("code") == 1409


@pytest.mark.asyncio
async def test_post_redirect_unauthorized(sanic_client: SanicASGITestClient, user_headers: dict[str, str]) -> None:
    _, res = await sanic_client.get("/api/data/platform/redirects")

    headers = user_headers
    payload = {"source_url": "/projects/ns/project-slug", "target_url": f"/p/{DUMMY_ULID}"}

    _, res = await sanic_client.post("/api/data/platform/redirects", headers=headers, json=payload)

    assert res.status_code == 403, res.status_code
