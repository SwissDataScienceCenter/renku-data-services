import pytest
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.renku_apps.k8s_client import KNATIVE_SERVICE_GVK

pytestmark = pytest.mark.skipif("not config.getoption('--enable-apps')", reason="Only run when --enable-apps is given")


async def test_app_lifecycle(
    sanic_client: SanicASGITestClient,
    app_manager_instance: DependencyManager,
    user_headers,
    create_project,
    create_session_launcher,
) -> None:
    project = await create_project(sanic_client, "App project", visibility="public")
    launcher = await create_session_launcher(
        "App launcher",
        project_id=project["id"],
        launcher_type="app",
        environment={
            "environment_kind": "CUSTOM",
            "name": "App environment",
            "container_image": "nginx:1.29",
            "environment_image_source": "image",
            "default_url": "/",
            "port": 8080,
            # Set so that the working directory is not read from the image registry over the network.
            "working_directory": "/app",
        },
    )

    _, res = await sanic_client.post("/api/data/apps", headers=user_headers, json={"launcher_id": launcher["id"]})

    assert res.status_code == 201, res.text
    app = res.json
    assert app["launcher_id"] == launcher["id"]
    assert app["project_id"] == project["id"]
    assert app["status"] == "pending"
    assert app.get("url") is None

    _, res = await sanic_client.get("/api/data/apps", headers=user_headers, params={"project_id": project["id"]})

    assert res.status_code == 200, res.text
    assert [existing["name"] for existing in res.json] == [app["name"]]

    knative_service = app_manager_instance.apps_k8s_pool.objects[(KNATIVE_SERVICE_GVK, app["name"])]
    knative_service.manifest.status = {
        "url": "https://app-project.renku.example.com",
        "conditions": [
            {"type": "Ready", "status": "True", "lastTransitionTime": "2026-08-19T10:00:00Z"},
        ],
    }

    _, res = await sanic_client.get(f"/api/data/apps/{app['name']}", headers=user_headers)

    assert res.status_code == 200, res.text
    assert res.json["status"] == "ready"
    assert res.json["url"] == "https://app-project.renku.example.com"
    assert res.json["started"] == "2026-08-19T10:00:00Z"

    _, res = await sanic_client.delete(f"/api/data/apps/{app['name']}", headers=user_headers)

    assert res.status_code == 204, res.text

    _, res = await sanic_client.get(f"/api/data/apps/{app['name']}", headers=user_headers)

    assert res.status_code == 404, res.text
