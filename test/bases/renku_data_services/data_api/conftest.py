import asyncio
import contextlib
import json
from collections.abc import AsyncGenerator, Callable
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from typing import Any, Protocol

import pytest
import pytest_asyncio
from authzed.api.v1 import Relationship, RelationshipUpdate, SubjectReference, WriteRelationshipsRequest
from httpx import Response
from sanic import Sanic
from sanic_testing.testing import SanicASGITestClient
from ulid import ULID

import renku_data_services.search.core as search_core
from renku_data_services.authz.admin_sync import sync_admins_from_keycloak
from renku_data_services.authz.authz import _AuthzConverter
from renku_data_services.base_models import Slug
from renku_data_services.base_models.core import APIUser, InternalServiceAdmin, NamespacePath, ServiceAdminId
from renku_data_services.data_api.app import register_all_handlers
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.data_connectors.apispec import DataConnector as ApiDataConnector
from renku_data_services.k8s.clients import K8sClusterClient
from renku_data_services.k8s.config import from_kubeconfig_file, get_clusters
from renku_data_services.k8s.constants import ClusterId
from renku_data_services.k8s.watcher import K8sWatcher, k8s_object_handler
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.namespace.apispec import GroupResponse as ApiGroup
from renku_data_services.namespace.models import UserNamespace
from renku_data_services.notebooks.constants import JUPYTER_SESSION_GVK
from renku_data_services.project.apispec import Project as ApiProject
from renku_data_services.search.apispec import SearchResult
from renku_data_services.secrets_storage_api.app import register_all_handlers as register_secrets_handlers
from renku_data_services.secrets_storage_api.dependencies import DependencyManager as SecretsDependencyManager
from renku_data_services.solr import entity_schema
from renku_data_services.solr.solr_client import DefaultSolrClient
from renku_data_services.solr.solr_migrate import SchemaMigrator
from renku_data_services.storage.rclone import RCloneValidator
from renku_data_services.users.dummy_kc_api import DummyKeycloakAPI
from renku_data_services.users.models import UserInfo
from renku_data_services.utils.middleware import validate_null_byte
from test.bases.renku_data_services.data_api.utils import KindCluster, setup_amalthea
from test.bases.renku_data_services.data_tasks.test_sync import get_kc_users
from test.utils import SanicReusableASGITestClient, TestDependencyManager


@pytest_asyncio.fixture(scope="session")
async def admin_user() -> UserInfo:
    return UserInfo(
        id="admin",
        first_name="Admin",
        last_name="Doe",
        email="admin.doe@gmail.com",
        namespace=UserNamespace(
            id=ULID(),
            underlying_resource_id="admin",
            created_by="admin",
            path=NamespacePath.from_strings("admin.doe"),
        ),
    )


@pytest_asyncio.fixture(scope="session")
async def regular_user() -> UserInfo:
    return UserInfo(
        id="user",
        first_name="User",
        last_name="Doe",
        email="user.doe@gmail.com",
        namespace=UserNamespace(
            id=ULID(),
            underlying_resource_id="user",
            created_by="user",
            path=NamespacePath.from_strings("user.doe"),
        ),
    )


@pytest_asyncio.fixture(scope="session")
async def member_1_user() -> UserInfo:
    return UserInfo(
        id="member-1",
        first_name="Member-1",
        last_name="Doe",
        email="member-1.doe@gmail.com",
        namespace=UserNamespace(
            id=ULID(),
            underlying_resource_id="member-1",
            created_by="member-1",
            path=NamespacePath.from_strings("member-1.doe"),
        ),
    )


@pytest_asyncio.fixture(scope="session")
async def member_2_user() -> UserInfo:
    return UserInfo(
        id="member-2",
        first_name="Member-2",
        last_name="Doe",
        email="member-2.doe@gmail.com",
        namespace=UserNamespace(
            id=ULID(),
            underlying_resource_id="member-2",
            created_by="member-2",
            path=NamespacePath.from_strings("member-2.doe"),
        ),
    )


@pytest_asyncio.fixture(scope="session")
async def project_members(member_1_user: UserInfo, member_2_user: UserInfo) -> list[dict[str, str]]:
    """List of a project's members."""
    return [{"id": member_1_user.id, "role": "viewer"}, {"id": member_2_user.id, "role": "owner"}]


@pytest_asyncio.fixture(scope="session")
async def users(admin_user, regular_user, member_1_user, member_2_user) -> list[UserInfo]:
    return [
        admin_user,
        regular_user,
        member_1_user,
        member_2_user,
    ]


@pytest_asyncio.fixture
async def admin_headers(admin_user: UserInfo) -> dict[str, str]:
    """Authentication headers for an admin user."""
    access_token = json.dumps(
        {
            "is_admin": True,
            "id": admin_user.id,
            "name": f"{admin_user.first_name} {admin_user.last_name}",
            "first_name": admin_user.first_name,
            "last_name": admin_user.last_name,
            "email": admin_user.email,
            "full_name": f"{admin_user.first_name} {admin_user.last_name}",
        }
    )
    return {"Authorization": f"Bearer {access_token}"}


@pytest_asyncio.fixture
async def user_headers(regular_user: UserInfo) -> dict[str, str]:
    """Authentication headers for a normal user."""
    access_token = json.dumps(
        {
            "is_admin": False,
            "id": regular_user.id,
            "name": f"{regular_user.first_name} {regular_user.last_name}",
            "first_name": regular_user.first_name,
            "last_name": regular_user.last_name,
            "email": regular_user.email,
            "full_name": f"{regular_user.first_name} {regular_user.last_name}",
        }
    )
    return {"Authorization": f"Bearer {access_token}"}


@pytest_asyncio.fixture
async def member_1_headers(member_1_user: UserInfo) -> dict[str, str]:
    """Authentication headers for a normal user."""
    access_token = json.dumps(
        {"is_admin": False, "id": member_1_user.id, "name": f"{member_1_user.first_name} {member_1_user.last_name}"}
    )
    return {"Authorization": f"Bearer {access_token}"}


@pytest_asyncio.fixture
async def member_2_headers(member_2_user: UserInfo) -> dict[str, str]:
    """Authentication headers for a normal user."""
    access_token = json.dumps(
        {"is_admin": False, "id": member_2_user.id, "name": f"{member_2_user.first_name} {member_2_user.last_name}"}
    )
    return {"Authorization": f"Bearer {access_token}"}


@pytest_asyncio.fixture
async def unauthorized_headers() -> dict[str, str]:
    """Authentication headers for an anonymous user (did not log in)."""
    return {"Authorization": "Bearer {}"}


@pytest.fixture
def headers_from_user(
    admin_user: UserInfo,
    admin_headers: dict[str, str],
    regular_user: UserInfo,
    user_headers: dict[str, str],
    member_1_user: UserInfo,
    member_1_headers: dict[str, str],
    member_2_user: UserInfo,
    member_2_headers: dict[str, str],
    unauthorized_headers: dict[str, str],
) -> Callable[[UserInfo], dict[str, str]]:
    def _headers_from_user(user: UserInfo) -> dict[str, str]:
        match user.id:
            case admin_user.id:
                return admin_headers
            case regular_user.id:
                return user_headers
            case member_1_user.id:
                return member_1_headers
            case member_2_user.id:
                return member_2_headers
            case _:
                return unauthorized_headers

    return _headers_from_user


@pytest_asyncio.fixture
async def bootstrap_admins(
    sanic_client_with_migrations, app_manager_instance: DependencyManager, event_loop, admin_user: UserInfo
) -> None:
    authz = app_manager_instance.authz
    rels: list[RelationshipUpdate] = []
    sub = SubjectReference(object=_AuthzConverter.user(admin_user.id))
    rels.append(
        RelationshipUpdate(
            operation=RelationshipUpdate.OPERATION_TOUCH,
            relationship=Relationship(resource=_AuthzConverter.platform(), relation="admin", subject=sub),
        )
    )
    await authz.client.WriteRelationships(WriteRelationshipsRequest(updates=rels))


@pytest_asyncio.fixture(scope="session")
async def sanic_app_no_migrations(app_manager: DependencyManager, users: list[UserInfo], admin_user: UserInfo) -> Sanic:
    app_manager.kc_api = DummyKeycloakAPI(users=get_kc_users(users), user_roles={admin_user.id: ["renku-admin"]})
    app = Sanic(app_manager.app_name)
    app = register_all_handlers(app, app_manager)
    app.register_middleware(validate_null_byte, "request")
    validator = RCloneValidator()
    app.ext.dependency(validator)
    return app


@pytest_asyncio.fixture(scope="session")
async def sanic_client_no_migrations(sanic_app_no_migrations: Sanic) -> AsyncGenerator[SanicASGITestClient, None]:
    async with SanicReusableASGITestClient(sanic_app_no_migrations) as client:
        yield client


@pytest_asyncio.fixture
async def sanic_client_with_migrations(
    sanic_client_no_migrations: SanicASGITestClient, app_manager_instance
) -> SanicASGITestClient:
    run_migrations_for_app("common")

    return sanic_client_no_migrations


@pytest_asyncio.fixture
async def sanic_client(
    sanic_client_with_migrations: SanicASGITestClient, app_manager_instance, bootstrap_admins
) -> SanicASGITestClient:
    await app_manager_instance.kc_user_repo.initialize(app_manager_instance.kc_api)
    await sync_admins_from_keycloak(app_manager_instance.kc_api, app_manager_instance.authz)
    await app_manager_instance.group_repo.generate_user_namespaces()
    return sanic_client_with_migrations


@pytest_asyncio.fixture
async def sanic_client_with_solr(sanic_client: SanicASGITestClient, app_manager) -> SanicASGITestClient:
    migrator = SchemaMigrator(app_manager.config.solr)
    await migrator.migrate(entity_schema.all_migrations)

    return sanic_client


class SearchReprovisionCall(Protocol):
    """The type for the `search_reprovision` fixture."""

    async def __call__(self) -> None: ...


@pytest_asyncio.fixture
async def search_reprovision(app_manager_instance: DependencyManager, search_push_updates) -> SearchReprovisionCall:
    admin = InternalServiceAdmin(id=ServiceAdminId.search_reprovision)

    async def search_reprovision_helper() -> None:
        await app_manager_instance.search_reprovisioning.run_reprovision(admin)
        await search_push_updates(clear_index=False)

    return search_reprovision_helper


@pytest_asyncio.fixture
async def search_push_updates(app_manager_instance: DependencyManager):
    async def search_push_updates_helper(clear_index: bool = True) -> None:
        async with DefaultSolrClient(app_manager_instance.config.solr) as client:
            if clear_index:
                await client.delete("*:*")
            await search_core.update_solr(app_manager_instance.search_updates_repo, client, 10)

    return search_push_updates_helper


class SearchQueryCall(Protocol):
    """The type for the `search_query` fixture."""

    async def __call__(self, query_str: str, user: UserInfo | None = None) -> SearchResult: ...


@pytest_asyncio.fixture
async def search_query(sanic_client_with_solr, admin_user: UserInfo) -> SearchQueryCall:
    async def search_query_helper(query_str: str, user: UserInfo | None = None) -> SearchResult:
        headers = __make_headers(user, admin=user.id == admin_user.id) if user is not None else {}
        _, response = await sanic_client_with_solr.get(
            "/api/data/search/query", params={"q": query_str}, headers=headers or {}
        )
        assert response.status_code == 200, response.text
        return SearchResult.model_validate(response.json)

    return search_query_helper


@pytest_asyncio.fixture
async def create_project(sanic_client, user_headers, admin_headers, regular_user, admin_user):
    async def create_project_helper(
        name: str,
        admin: bool = False,
        members: list[dict[str, str]] | None = None,
        description: str | None = None,
        sanic_client=sanic_client,
        **payload,
    ) -> dict[str, Any]:
        if members is None:
            members = []
        headers = admin_headers if admin else user_headers
        user = admin_user if admin else regular_user
        payload = payload.copy()
        if "name" not in payload:
            payload.update({"name": name})
        if "namespace" not in payload:
            payload.update({"namespace": f"{user.first_name}.{user.last_name}".lower()})
        if "description" not in payload and description is not None:
            payload.update({"description": description})

        _, response = await sanic_client.post("/api/data/projects", headers=headers, json=payload)

        assert response.status_code == 201, response.text
        project = response.json

        if members:
            _, response = await sanic_client.patch(
                f"/api/data/projects/{project['id']}/members", headers=headers, json=members
            )

            assert response.status_code == 200, response.text

        return project

    return create_project_helper


class CreateProjectCall(Protocol):
    async def __call__(
        self,
        name: str,
        user: UserInfo | None = None,
        members: list[dict[str, str]] | None = None,
        **payload,
    ) -> ApiProject: ...


@pytest_asyncio.fixture
async def create_project_model(sanic_client, regular_user: UserInfo, admin_user: UserInfo) -> CreateProjectCall:
    async def create_project_helper(
        name: str, user: UserInfo | None = None, members: list[dict[str, str]] | None = None, **payload
    ) -> ApiProject:
        if "name" not in payload:
            payload.update({"name": name})

        user = user or regular_user
        headers = __make_headers(user, admin=user.id == admin_user.id)
        if "namespace" not in payload:
            payload.update({"namespace": user.namespace.path.serialize()})

        _, response = await sanic_client.post("/api/data/projects", headers=headers, json=payload)

        assert response.status_code == 201, response.text
        project = response.json

        if members:
            _, response = await sanic_client.patch(
                f"/api/data/projects/{project['id']}/members", headers=headers, json=members
            )

            assert response.status_code == 200, response.text

        return ApiProject.model_validate(project)

    return create_project_helper


class CreateUserCall(Protocol):
    async def __call__(self, user: APIUser) -> UserInfo: ...


@pytest_asyncio.fixture
async def create_user(app_manager_instance: TestDependencyManager) -> CreateUserCall:
    repo = app_manager_instance.kc_user_repo

    async def create_user_helper(user: APIUser) -> UserInfo:
        info = await repo.get_or_create_user(user, user.id or "")
        if info is None:
            raise Exception(f"User {user} could not be created")
        return info

    return create_user_helper


@pytest_asyncio.fixture
async def create_project_copy(sanic_client, user_headers, headers_from_user):
    async def create_project_copy_helper(
        id: str,
        namespace: str,
        name: str,
        *,
        user: UserInfo | None = None,
        members: list[dict[str, str]] = None,
        **payload,
    ) -> dict[str, Any]:
        headers = headers_from_user(user) if user is not None else user_headers
        copy_payload = {"slug": Slug.from_name(name).value}
        copy_payload.update(payload)
        copy_payload.update({"namespace": namespace, "name": name})

        _, response = await sanic_client.post(f"/api/data/projects/{id}/copies", headers=headers, json=copy_payload)
        assert response.status_code == 201, response.text
        project = response.json

        if members:
            _, response = await sanic_client.patch(
                f"/api/data/projects/{project['id']}/members", headers=headers, json=members
            )
            assert response.status_code == 200, response.text

        return project

    return create_project_copy_helper


@pytest_asyncio.fixture
async def create_group(sanic_client, user_headers, admin_headers):
    async def create_group_helper(
        name: str, admin: bool = False, members: list[dict[str, str]] = None, **payload
    ) -> dict[str, Any]:
        headers = admin_headers if admin else user_headers
        group_payload = {"slug": Slug.from_name(name).value}
        group_payload.update(payload)
        group_payload.update({"name": name})

        _, response = await sanic_client.post("/api/data/groups", headers=headers, json=group_payload)

        assert response.status_code == 201, response.text
        group = response.json

        if members:
            _, response = await sanic_client.patch(
                f"/api/data/groups/{group['slug']}/members", headers=headers, json=members
            )

            assert response.status_code == 200, response.text

        return group

    return create_group_helper


class CreateGroupCall(Protocol):
    async def __call__(
        self, name: str, user: UserInfo | None = None, members: list[dict[str, str]] | None = None, **payload
    ) -> ApiGroup: ...


@pytest_asyncio.fixture
async def create_group_model(sanic_client, regular_user: UserInfo, admin_user: UserInfo) -> CreateGroupCall:
    async def create_group_helper(
        name: str, user: UserInfo | None = None, members: list[dict[str, str]] | None = None, **payload
    ) -> ApiGroup:
        user = user or regular_user
        headers = __make_headers(user, admin=user.id == admin_user.id)
        group_payload = {"slug": Slug.from_name(name).value, "name": name}
        group_payload.update(payload)
        _, response = await sanic_client.post("/api/data/groups", headers=headers, json=group_payload)

        assert response.status_code == 201, response.text
        group = response.json

        if members:
            _, response = await sanic_client.patch(
                f"/api/data/groups/{group['slug']}/members", headers=headers, json=members
            )

            assert response.status_code == 200, response.text

        return ApiGroup.model_validate(group)

    return create_group_helper


@pytest_asyncio.fixture
async def create_session_environment(sanic_client: SanicASGITestClient, admin_headers):
    async def create_session_environment_helper(name: str, **payload) -> dict[str, Any]:
        payload = payload.copy()
        payload.update({"name": name})
        payload["description"] = payload.get("description") or "A session environment."
        payload["container_image"] = payload.get("container_image") or "some_image:some_tag"
        payload["environment_image_source"] = payload.get("environment_image_source") or "image"

        _, res = await sanic_client.post("/api/data/environments", headers=admin_headers, json=payload)

        assert res.status_code == 201, res.text
        assert res.json is not None
        return res.json

    return create_session_environment_helper


@pytest_asyncio.fixture
async def create_session_launcher(sanic_client: SanicASGITestClient, user_headers):
    async def create_session_launcher_helper(name: str, project_id: str, **payload) -> dict[str, Any]:
        payload = payload.copy()
        payload.update({"name": name, "project_id": project_id})
        payload["description"] = payload.get("description") or "A session launcher."
        if "environment" not in payload:
            payload["environment"] = {
                "environment_kind": "CUSTOM",
                "name": "Test",
                "container_image": "some_image:some_tag",
                "environment_image_source": "image",
            }

        _, res = await sanic_client.post("/api/data/session_launchers", headers=user_headers, json=payload)

        assert res.status_code == 201, res.text
        assert res.json is not None
        return res.json

    return create_session_launcher_helper


@pytest_asyncio.fixture
async def create_data_connector(sanic_client: SanicASGITestClient, regular_user: UserInfo, user_headers):
    async def create_data_connector_helper(
        name: str, user: UserInfo | None = None, headers: dict[str, str] | None = None, **payload
    ) -> dict[str, Any]:
        user = user or regular_user
        headers = headers or user_headers
        dc_payload = {
            "name": name,
            "description": "A data connector",
            "visibility": "private",
            "namespace": user.namespace.path.serialize(),
            "storage": {
                "configuration": {
                    "type": "s3",
                    "provider": "AWS",
                    "region": "us-east-1",
                },
                "source_path": "bucket/my-folder",
                "target_path": "my/target",
            },
            "keywords": ["keyword 1", "keyword.2", "keyword-3", "KEYWORD_4"],
        }
        dc_payload.update(payload)

        _, response = await sanic_client.post("/api/data/data_connectors", headers=headers, json=dc_payload)

        assert response.status_code == 201, response.text
        return response.json

    return create_data_connector_helper


class CreateDataConnectorCall(Protocol):
    async def __call__(self, name: str, user: UserInfo | None = None, **payload) -> ApiDataConnector: ...


@pytest_asyncio.fixture
async def create_data_connector_model(
    sanic_client: SanicASGITestClient, regular_user: UserInfo, admin_user: UserInfo
) -> CreateDataConnectorCall:
    async def create_dc_helper(name: str, user: UserInfo | None = None, **payload) -> ApiDataConnector:
        user = user or regular_user
        headers = __make_headers(user, admin=user.id == admin_user.id)
        dc_payload = {
            "name": name,
            "visibility": "private",
            "namespace": user.namespace.path.serialize(),
            "storage": {
                "configuration": {
                    "type": "s3",
                    "provider": "AWS",
                    "region": "us-east-1",
                },
                "source_path": "bucket/my-folder",
                "target_path": "my/target",
            },
            "keywords": [],
        }
        dc_payload.update(payload)
        _, response = await sanic_client.post("/api/data/data_connectors", headers=headers, json=dc_payload)

        assert response.status_code == 201, response.text
        return ApiDataConnector.model_validate(response.json)

    return create_dc_helper


@pytest_asyncio.fixture
async def create_data_connector_and_link_project(
    regular_user, user_headers, admin_user, admin_headers, create_data_connector, link_data_connector
):
    async def create_data_connector_and_link_project_helper(
        name: str, project_id: str, admin: bool = False, **payload
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        headers = admin_headers if admin else user_headers
        user = admin_user if admin else regular_user

        data_connector = await create_data_connector(name, user=user, headers=headers, **payload)
        data_connector_id = data_connector["id"]
        response = await link_data_connector(project_id, data_connector_id, headers=headers)
        data_connector_link = response.json

        return data_connector, data_connector_link

    return create_data_connector_and_link_project_helper


@pytest.fixture
def link_data_connector(sanic_client: SanicASGITestClient):
    async def _link_data_connector(project_id: str, dc_id: str, headers: dict[str, str]) -> Response:
        payload = {"project_id": project_id}
        _, response = await sanic_client.post(
            f"/api/data/data_connectors/{dc_id}/project_links", headers=headers, json=payload
        )
        assert response.status_code == 201, response.text
        return response

    return _link_data_connector


@pytest_asyncio.fixture
async def create_session_secret_slot(sanic_client: SanicASGITestClient, user_headers: dict[str, str]):
    async def create_session_secret_slot_helper(
        filename: str, project_id: str, **payload: dict[str, Any]
    ) -> dict[str, Any]:
        payload = payload.copy()
        payload.update({"filename": filename, "project_id": project_id})
        payload["description"] = payload.get("description") or "A secret slot."

        _, res = await sanic_client.post("/api/data/session_secret_slots", headers=user_headers, json=payload)

        assert res.status_code == 201, res.text
        assert res.json is not None
        return res.json

    return create_session_secret_slot_helper


@pytest_asyncio.fixture
async def create_resource_pool(sanic_client, user_headers, admin_headers, valid_resource_pool_payload):
    async def create_resource_pool_helper(admin: bool = False, **payload) -> dict[str, Any]:
        headers = admin_headers if admin else user_headers
        valid_resource_pool_payload.update(payload)
        _, res = await sanic_client.post("/api/data/resource_pools", headers=headers, json=valid_resource_pool_payload)
        assert res.status_code == 201, res.text
        assert res.json is not None
        return res.json

    return create_resource_pool_helper


_valid_resource_pool_payload: dict[str, Any] = {
    "name": "test-name",
    "classes": [
        {
            "cpu": 1.0,
            "memory": 10,
            "gpu": 0,
            "name": "test-class-name",
            "max_storage": 100,
            "default_storage": 1,
            "default": True,
            "node_affinities": [],
            "tolerations": [],
        },
        {
            "cpu": 2.0,
            "memory": 20,
            "gpu": 0,
            "name": "test-class-name",
            "max_storage": 200,
            "default_storage": 2,
            "default": False,
            "node_affinities": [],
            "tolerations": [],
        },
    ],
    "quota": {"cpu": 100, "memory": 100, "gpu": 0},
    "default": False,
    "public": True,
    "idle_threshold": 86400,
    "hibernation_threshold": 99999,
}


@pytest_asyncio.fixture
async def valid_resource_pool_payload() -> dict[str, Any]:
    return deepcopy(_valid_resource_pool_payload)


@pytest_asyncio.fixture
async def valid_resource_class_payload() -> dict[str, Any]:
    return deepcopy(_valid_resource_pool_payload["classes"][0])


@pytest_asyncio.fixture
async def secrets_sanic_client(
    secrets_storage_app_manager: SecretsDependencyManager, users: list[UserInfo]
) -> AsyncGenerator[SanicASGITestClient, None]:
    app = Sanic(secrets_storage_app_manager.config.app_name)
    app = register_secrets_handlers(app, secrets_storage_app_manager)
    async with SanicReusableASGITestClient(app) as client:
        yield client


def pytest_addoption(parser):
    parser.addoption("--disable-cluster-creation", action="store_true", default=False, help="Disable cluster creation")


@pytest_asyncio.fixture(scope="session")
def disable_cluster_creation(request):
    return request.config.getoption("--disable-cluster-creation")


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


@pytest.fixture(scope="session")
def cluster_name():
    return f"k8s-cluster-{str(ULID()).lower()}"


@pytest.fixture(scope="session")
def kubeconfig_path(monkeysession):
    kconf = ".kind-kubeconfig.yaml"
    monkeysession.setenv("KUBECONFIG", kconf)
    return Path(kconf)


@pytest.fixture(scope="session")
def cluster(cluster_name, kubeconfig_path):
    with KindCluster(cluster_name, kubeconfig=str(kubeconfig_path)) as cluster:
        yield cluster


@pytest.fixture(scope="session")
def amalthea_installation(cluster):
    setup_amalthea("amalthea", "amalthea", "0.22.0", cluster)


@pytest_asyncio.fixture
async def jupyter_server_k8s_watcher(cluster, amalthea_installation, app_manager_instance):
    app_manager = app_manager_instance
    default_kubeconfig = await from_kubeconfig_file(cluster.kubeconfig)
    clusters: dict[ClusterId, K8sClusterClient] = {}
    async for client in get_clusters(
        kube_conf_root_dir=app_manager.config.k8s_config_root,
        default_kubeconfig=default_kubeconfig,
        cluster_repo=app_manager.cluster_repo,
    ):
        clusters[client.get_cluster().id] = client

    # sleep to give amalthea a chance to create the CRDs, otherwise the watcher can error out
    await asyncio.sleep(1)
    watcher = K8sWatcher(
        handler=k8s_object_handler(app_manager.config.nb_config.k8s_db_cache, app_manager.metrics, app_manager.rp_repo),
        clusters=clusters,
        kinds=[JUPYTER_SESSION_GVK],
        db_cache=app_manager.config.nb_config.k8s_db_cache,
    )
    asyncio.create_task(watcher.start())
    yield
    with contextlib.suppress(TimeoutError):
        await watcher.stop(timeout=timedelta(seconds=1))
