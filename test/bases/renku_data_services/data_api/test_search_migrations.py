from collections.abc import Callable
from re import L

import pytest
import pytest_asyncio
from sanic import Sanic
from sanic_testing.testing import SanicASGITestClient
from ulid import ULID

from renku_data_services.authz.admin_sync import sync_admins_from_keycloak
from renku_data_services.base_models.core import APIUser
from renku_data_services.data_api.app import register_all_handlers
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.solr import entity_schema
from renku_data_services.solr.solr_migrate import SchemaMigration, SchemaMigrator
from renku_data_services.storage.rclone import RCloneValidator
from renku_data_services.users.dummy_kc_api import DummyKeycloakAPI
from renku_data_services.users.models import UserInfo
from renku_data_services.utils.middleware import validate_null_byte
from test.bases.renku_data_services.data_api.conftest import (
    CreateGroupCall,
    CreateProjectCall,
    CreateUserCall,
    SearchQueryCall,
    SearchReprovisionCall,
)
from test.bases.renku_data_services.data_api.test_search import assert_search_result
from test.bases.renku_data_services.data_tasks.test_sync import get_kc_users
from test.utils import SanicReusableASGITestClient, TestDependencyManager


@pytest.fixture
def app_manager(monkeypatch, worker_id, dummy_users, solr_core):
    monkeypatch.setenv("DUMMY_STORES", "true")
    monkeypatch.setenv("MAX_PINNED_PROJECTS", "5")
    monkeypatch.setenv("NB_SERVER_OPTIONS__DEFAULTS_PATH", "server_defaults.json")
    monkeypatch.setenv("NB_SERVER_OPTIONS__UI_CHOICES_PATH", "server_options.json")
    monkeypatch.setenv("V1_SESSIONS_ENABLED", "true")

    dm = TestDependencyManager.from_env(dummy_users)

    app_name = "app_" + str(ULID()).lower() + "_" + worker_id
    dm.app_name = app_name
    return dm


@pytest_asyncio.fixture
@pytest.mark.xdist_group("search")
async def sanic_client(
    authz_setup,
    secrets_key_pair,
    db_instance,
    authz_instance,
    users: list[UserInfo],
    admin_user: UserInfo,
    app_manager: TestDependencyManager,
):
    run_migrations_for_app("common")
    dm = app_manager
    dm.kc_api = DummyKeycloakAPI(users=get_kc_users(users), user_roles={admin_user.id: ["renku-admin"]})
    app = Sanic(dm.app_name)
    app = register_all_handlers(app, dm)
    app.register_middleware(validate_null_byte, "request")
    validator = RCloneValidator()
    app.ext.dependency(validator)
    await dm.kc_user_repo.initialize(dm.kc_api)
    await sync_admins_from_keycloak(dm.kc_api, dm.authz)
    await dm.group_repo.generate_user_namespaces()
    async with SanicReusableASGITestClient(app) as client:
        yield client


@pytest.fixture
def get_solr_schemas() -> Callable[[int | None], list[SchemaMigration]]:
    def _helper(latest_version: int | None = None) -> list[SchemaMigration]:
        if latest_version is None:
            return entity_schema.all_migrations
        return [i for i in entity_schema.all_migrations if i.version <= latest_version]

    return _helper


@pytest.mark.xdist_group("search")
@pytest.mark.asyncio
async def test_search_schema_upgrade_13_to_15(
    create_user: CreateUserCall,
    regular_user: UserInfo,
    search_reprovision: SearchReprovisionCall,
    create_project_model: CreateProjectCall,
    create_group_model: CreateGroupCall,
    search_query: SearchQueryCall,
    sanic_client: SanicASGITestClient,
    app_manager: TestDependencyManager,
    get_solr_schemas: Callable[[int | None], list[SchemaMigration]],
) -> None:
    solr_migrator = SchemaMigrator(app_manager.config.solr)
    res = await solr_migrator.migrate(get_solr_schemas(13))
    assert res.migrations_run == 13 - 9 + 1  # Migrations start at version 9
    mads = await create_user(app_manager, APIUser(id="mads-123", first_name="Mads", last_name="Pedersen"))
    wout = await create_user(app_manager, APIUser(id="wout-567", first_name="Wout", last_name="van Art"))
    gr_lidl = await create_group_model(
        sanic_client,
        "Lidl-Trek",
        members=[{"id": mads.id, "role": "editor"}, {"id": wout.id, "role": "viewer"}],
        user=regular_user,
    )

    p1 = await create_project_model(
        sanic_client,
        "project za",
        mads,
        visibility="public",
        members=[{"id": wout.id, "role": "editor"}],
        namespace=gr_lidl.slug,
    )
    p3 = await create_project_model(
        sanic_client,
        "project zc",
        mads,
        visibility="public",
        namespace=gr_lidl.slug,
        members=[{"id": wout.id, "role": "editor"}],
    )

    await search_reprovision(app_manager)
    result = await search_query(sanic_client, f"namespace:{gr_lidl.slug}", user=wout)
    assert_search_result(result, [p1, p3])
