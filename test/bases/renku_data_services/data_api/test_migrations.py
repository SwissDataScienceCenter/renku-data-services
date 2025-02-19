import base64
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from alembic.script import ScriptDirectory
from sanic_testing.testing import SanicASGITestClient
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import bindparam
from ulid import ULID

from renku_data_services.app_config.config import Config
from renku_data_services.message_queue.avro_models.io.renku.events import v2
from renku_data_services.message_queue.models import deserialize_binary
from renku_data_services.migrations.core import downgrade_migrations_for_app, get_alembic_config, run_migrations_for_app
from renku_data_services.users.models import UserInfo


@pytest.mark.asyncio
async def test_unique_migration_head() -> None:
    cfg = get_alembic_config(name="common")
    script = ScriptDirectory.from_config(cfg)

    heads = script.get_revisions(script.get_heads())
    heads = [h.revision for h in heads]

    assert len(heads) == 1, f"Found more than one revision heads {heads}"


@pytest.mark.asyncio
async def test_upgrade_downgrade_cycle(
    app_config_instance: Config,
    sanic_client_no_migrations: SanicASGITestClient,
    admin_headers: dict,
    admin_user: UserInfo,
) -> None:
    # Migrate to head and create a project
    run_migrations_for_app("common", "head")
    await app_config_instance.kc_user_repo.initialize(app_config_instance.kc_api)
    await app_config_instance.group_repo.generate_user_namespaces()
    payload: dict[str, Any] = {
        "name": "test_project",
        "namespace": admin_user.namespace.slug,
    }
    _, res = await sanic_client_no_migrations.post("/api/data/projects", headers=admin_headers, json=payload)
    assert res.status_code == 201
    # Migrate/downgrade a few times but end on head
    downgrade_migrations_for_app("common", "base")
    run_migrations_for_app("common", "head")
    downgrade_migrations_for_app("common", "base")
    run_migrations_for_app("common", "head")
    # Try to make the same project again
    # NOTE: The engine has to be disposed otherwise it caches the postgres types (i.e. enums)
    # from previous migrations and then trying to create a project below fails with the message
    # cache postgres lookup failed for type XXXX.
    await app_config_instance.db.current._async_engine.dispose()
    await app_config_instance.kc_user_repo.initialize(app_config_instance.kc_api)
    await app_config_instance.group_repo.generate_user_namespaces()
    _, res = await sanic_client_no_migrations.post("/api/data/projects", headers=admin_headers, json=payload)
    assert res.status_code == 201, res.json


# !IMPORTANT: This test can only be run on v2 of the authz schema
@pytest.mark.skip
@pytest.mark.asyncio
async def test_migration_to_f34b87ddd954(
    sanic_client_no_migrations: SanicASGITestClient,
    app_config_instance: Config,
    user_headers: dict,
    admin_headers: dict,
) -> None:
    run_migrations_for_app("common", "d8676f0cde53")
    await app_config_instance.kc_user_repo.initialize(app_config_instance.kc_api)
    await app_config_instance.group_repo.generate_user_namespaces()
    sanic_client = sanic_client_no_migrations
    payloads = [
        {
            "name": "Group1",
            "slug": "group-1",
            "description": "Group 1 Description",
        },
        {
            "name": "Group2",
            "slug": "group-2",
            "description": "Group 2 Description",
        },
    ]
    added_group_ids = []
    for payload in payloads:
        _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
        assert response.status_code == 201
        added_group_ids.append(response.json["id"])
    run_migrations_for_app("common", "f34b87ddd954")
    # The migration should delete all groups
    _, response = await sanic_client.get("/api/data/groups", headers=user_headers)
    assert response.status_code == 200
    assert len(response.json) == 0
    # The database should have delete events for the groups
    events_orm = await app_config_instance.event_repo.get_pending_events()
    group_removed_events = [
        deserialize_binary(base64.b64decode(e.payload["payload"]), v2.GroupRemoved)
        for e in events_orm
        if e.queue == "group.removed"
    ]
    assert len(group_removed_events) == 2
    assert set(added_group_ids) == {e.id for e in group_removed_events}


@pytest.mark.asyncio
async def test_migration_to_1ef98b967767_and_086eb60b42c8(app_config_instance: Config, admin_user: UserInfo) -> None:
    """Tests the migration of the session launchers."""
    run_migrations_for_app("common", "b8cbd62e85b9")
    await app_config_instance.kc_user_repo.initialize(app_config_instance.kc_api)
    await app_config_instance.group_repo.generate_user_namespaces()
    global_env_id = str(ULID())
    custom_launcher_id = str(ULID())
    global_launcher_id = str(ULID())
    project_id = str(ULID())
    async with app_config_instance.db.async_session_maker() as session, session.begin():
        await session.execute(
            sa.text(
                "INSERT INTO "
                "projects.projects(id, name, visibility, created_by_id, creation_date) "
                "VALUES(:id, :name, 'public', :created_by, :date)"
            ).bindparams(
                id=project_id,
                name="test_project",
                created_by=admin_user.id,
                date=datetime.now(UTC),
            )
        )
        await session.execute(
            sa.text(
                "INSERT INTO "
                "sessions.environments(id, name, created_by_id, creation_date, container_image, default_url) "
                "VALUES (:id, :name, :created_by, :date, :container_image, :default_url)"
            ).bindparams(
                id=global_env_id,
                name="global env",
                created_by=admin_user.id,
                date=datetime.now(UTC),
                container_image="global_env_image",
                default_url="/global_env_url",
            )
        )
        await session.execute(
            sa.text(
                "INSERT INTO "
                "sessions.launchers("
                "id, name, created_by_id, creation_date, environment_kind, environment_id, project_id"
                ") "
                "VALUES (:id, :name, :created_by, :date, 'global_environment', :environment_id, :project_id)"
            ).bindparams(
                id=global_launcher_id,
                name="global",
                created_by=admin_user.id,
                date=datetime.now(UTC),
                environment_id=global_env_id,
                project_id=project_id,
            )
        )
        await session.execute(
            sa.text(
                "INSERT INTO "
                "sessions.launchers("
                "id, name, created_by_id, creation_date, environment_kind, container_image, default_url, project_id"
                ") "
                "VALUES ("
                ":id, :name, :created_by, :date, 'container_image', :container_image, :default_url, :project_id"
                ")"
            ).bindparams(
                id=custom_launcher_id,
                name="custom",
                created_by=admin_user.id,
                date=datetime.now(UTC),
                container_image="custom_image",
                default_url="/custom_env_url",
                project_id=project_id,
            )
        )
    run_migrations_for_app("common", "1ef98b967767")
    async with app_config_instance.db.async_session_maker() as session, session.begin():
        res = await session.execute(
            sa.text("SELECT * FROM sessions.environments WHERE name = :name").bindparams(name="global env")
        )
    data = res.all()
    assert len(data) == 1
    global_env = data[0]._mapping
    assert global_env["id"] == global_env_id
    assert global_env["name"] == "global env"
    assert global_env["container_image"] == "global_env_image"
    assert global_env["default_url"] == "/global_env_url"
    assert global_env["port"] == 8888
    assert global_env["uid"] == 1000
    assert global_env["gid"] == 100
    assert global_env["command"] == ["sh", "-c"]
    assert global_env["args"] == [
        "/entrypoint.sh jupyter server --ServerApp.ip=0.0.0.0 --ServerApp.port=8888 "
        "--ServerApp.base_url=$RENKU_BASE_URL_PATH "
        '--ServerApp.token="" --ServerApp.password="" --ServerApp.allow_remote_access=true '
        "--ContentsManager.allow_hidden=true --ServerApp.allow_origin=*",
    ]
    assert global_env["environment_kind"] == "GLOBAL"
    async with app_config_instance.db.async_session_maker() as session, session.begin():
        res = await session.execute(
            sa.text("SELECT * FROM sessions.environments WHERE name != :name").bindparams(name="global env")
        )
    data = res.all()
    assert len(data) == 1
    custom_env = data[0]._mapping
    assert custom_env["name"].startswith("Custom environment for session launcher")
    assert custom_env["container_image"] == "custom_image"
    assert custom_env["default_url"] == "/custom_env_url"
    assert custom_env["port"] == 8888
    assert custom_env["uid"] == 1000
    assert custom_env["gid"] == 100
    assert custom_env["command"] == ["sh", "-c"]
    assert custom_env["args"] == [
        "/entrypoint.sh jupyter server --ServerApp.ip=0.0.0.0 --ServerApp.port=8888 "
        "--ServerApp.base_url=$RENKU_BASE_URL_PATH "
        '--ServerApp.token="" --ServerApp.password="" --ServerApp.allow_remote_access=true '
        "--ContentsManager.allow_hidden=true --ServerApp.allow_origin=*",
    ]
    assert custom_env["environment_kind"] == "CUSTOM"
    async with app_config_instance.db.async_session_maker() as session, session.begin():
        res = await session.execute(
            sa.text("SELECT * FROM sessions.launchers WHERE id = :id").bindparams(id=custom_launcher_id)
        )
    data = res.all()
    assert len(data) == 1
    custom_launcher = data[0]._mapping
    assert custom_launcher["name"] == "custom"
    assert custom_launcher["project_id"] == project_id
    assert custom_launcher["environment_id"] == custom_env["id"]
    async with app_config_instance.db.async_session_maker() as session, session.begin():
        res = await session.execute(
            sa.text("SELECT * FROM sessions.launchers WHERE id = :id").bindparams(id=global_launcher_id)
        )
    data = res.all()
    assert len(data) == 1
    global_launcher = data[0]._mapping
    assert global_launcher["name"] == "global"
    assert global_launcher["project_id"] == project_id
    assert global_launcher["environment_id"] == global_env["id"]
    run_migrations_for_app("common", "086eb60b42c8")
    async with app_config_instance.db.async_session_maker() as session, session.begin():
        res = await session.execute(
            sa.text("SELECT * FROM sessions.environments WHERE name = :name").bindparams(name="global env")
        )
    data = res.all()
    assert len(data) == 1
    global_env = data[0]._mapping
    assert global_env["args"] == [
        "/entrypoint.sh jupyter server --ServerApp.ip=0.0.0.0 --ServerApp.port=8888 "
        "--ServerApp.base_url=$RENKU_BASE_URL_PATH "
        '--ServerApp.token="" --ServerApp.password="" --ServerApp.allow_remote_access=true '
        '--ContentsManager.allow_hidden=true --ServerApp.allow_origin=* --ServerApp.root_dir="/home/jovyan/work"',
    ]


@pytest.mark.asyncio
async def test_migration_create_global_envs(
    app_config_instance: Config,
    sanic_client_no_migrations: SanicASGITestClient,
    admin_headers: dict,
    admin_user: UserInfo,
    tmpdir_factory,
    monkeysession,
) -> None:
    run_migrations_for_app("common", "head")
    envs = await app_config_instance.session_repo.get_environments()
    assert len(envs) == 2
    assert any(e.name == "Python/Jupyter" for e in envs)
    assert any(e.name == "Rstudio" for e in envs)


@pytest.mark.asyncio
async def test_migration_to_75c83dd9d619(app_config_instance: Config, admin_user: UserInfo) -> None:
    """Tests the migration for copying session environments of copied projects."""

    async def insert_project(session: AsyncSession, payload: dict[str, Any]) -> None:
        bindparams: list[sa.BindParameter] = []
        cols: list[str] = list(payload.keys())
        cols_joined = ", ".join(cols)
        ids = ", ".join([":" + col for col in cols])
        if "visibility" in payload:
            bindparams.append(bindparam("visibility", literal_execute=True))
        stmt = sa.text(
            f"INSERT INTO projects.projects({cols_joined}) VALUES({ids})",
        ).bindparams(*bindparams, **payload)
        await session.execute(stmt)

    async def insert_environment(session: AsyncSession, payload: dict[str, Any]) -> None:
        bindparams: list[sa.BindParameter] = []
        cols: list[str] = list(payload.keys())
        cols_joined = ", ".join(cols)
        ids = ", ".join([":" + col for col in cols])
        if "command" in payload:
            bindparams.append(bindparam("command", type_=JSONB))
        if "args" in payload:
            bindparams.append(bindparam("args", type_=JSONB))
        if "environment_kind" in payload:
            bindparams.append(bindparam("environment_kind", literal_execute=True))
        stmt = sa.text(f"INSERT INTO sessions.environments({cols_joined}) VALUES ({ids})").bindparams(
            *bindparams,
            **payload,
        )
        await session.execute(stmt)

    async def insert_session_launcher(session: AsyncSession, payload: dict[str, Any]) -> None:
        cols: list[str] = list(payload.keys())
        cols_joined = ", ".join(cols)
        ids = ", ".join([":" + col for col in cols])
        stmt = sa.text(f"INSERT INTO sessions.launchers({cols_joined}) VALUES ({ids})").bindparams(
            **payload,
        )
        await session.execute(stmt)

    run_migrations_for_app("common", "450ae3930996")
    await app_config_instance.kc_user_repo.initialize(app_config_instance.kc_api)
    await app_config_instance.group_repo.generate_user_namespaces()
    custom_launcher_id = str(ULID())
    custom_launcher_id_cloned = str(ULID())
    project_id = str(ULID())
    cloned_project_id = str(ULID())
    custom_env_id = str(ULID())
    random_project_id = str(ULID())
    random_env_id = str(ULID())
    random_launcher_id = str(ULID())
    async with app_config_instance.db.async_session_maker() as session, session.begin():
        # Create template project
        await insert_project(
            session,
            dict(
                id=project_id,
                name="test_project",
                created_by_id=admin_user.id,
                creation_date=datetime.now(UTC),
                visibility="public",
            ),
        )
        # Create clone project
        await insert_project(
            session,
            dict(
                id=cloned_project_id,
                name="cloned_project",
                created_by_id="some-other-user-id",
                creation_date=datetime.now(UTC),
                visibility="public",
                template_id=project_id,
            ),
        )
        # Create unrelated project
        await insert_project(
            session,
            dict(
                id=random_project_id,
                name="random_project",
                created_by_id=admin_user.id,
                creation_date=datetime.now(UTC),
                visibility="public",
            ),
        )
        # Create a single environment
        await insert_environment(
            session,
            dict(
                id=custom_env_id,
                name="custom env",
                created_by_id=admin_user.id,
                creation_date=datetime.now(UTC),
                container_image="env_image",
                default_url="/env_url",
                port=8888,
                args=["arg1"],
                command=["command1"],
                uid=1000,
                gid=1000,
                environment_kind="CUSTOM",
            ),
        )
        # Create an unrelated environment
        await insert_environment(
            session,
            dict(
                id=random_env_id,
                name="random env",
                created_by_id=admin_user.id,
                creation_date=datetime.now(UTC),
                container_image="env_image",
                default_url="/env_url",
                port=8888,
                args=["arg1"],
                command=["command1"],
                uid=1000,
                gid=1000,
                environment_kind="CUSTOM",
            ),
        )
        # Create two session launchers for each project, but both are using the same env
        await insert_session_launcher(
            session,
            dict(
                id=custom_launcher_id,
                name="custom",
                created_by_id=admin_user.id,
                creation_date=datetime.now(UTC),
                environment_id=custom_env_id,
                project_id=project_id,
            ),
        )
        await insert_session_launcher(
            session,
            dict(
                id=custom_launcher_id_cloned,
                name="custom_for_cloned_project",
                created_by_id=admin_user.id,
                creation_date=datetime.now(UTC),
                environment_id=custom_env_id,
                project_id=cloned_project_id,
            ),
        )
        # Create an unrelated session launcher that should be unaffected by the migrations
        await insert_session_launcher(
            session,
            dict(
                id=random_launcher_id,
                name="random_launcher",
                created_by_id=admin_user.id,
                creation_date=datetime.now(UTC),
                environment_id=random_env_id,
                project_id=random_project_id,
            ),
        )
    run_migrations_for_app("common", "75c83dd9d619")
    async with app_config_instance.db.async_session_maker() as session, session.begin():
        launchers = (await session.execute(sa.text("SELECT environment_id, name FROM sessions.launchers"))).all()
        envs = (
            await session.execute(
                sa.text("SELECT created_by_id, id, name FROM sessions.environments WHERE environment_kind = 'CUSTOM'")
            )
        ).all()
    assert len(launchers) == 3
    assert len(envs) == 3
    # Check that the launcher that does not need changes is unchanged
    assert launchers[1][0] == random_env_id
    assert launchers[1][1] == "random_launcher"
    assert envs[1][0] == admin_user.id
    assert envs[1][1] == random_env_id
    # Check that each of the launchers refers to a separate environment
    assert launchers[0][0] == custom_env_id
    assert launchers[0][0] != launchers[2][0]
    assert envs[0][0] == admin_user.id
    assert envs[2][0] == "some-other-user-id"
