import random
import string
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

import pytest
import sqlalchemy as sa
from alembic.script import ScriptDirectory
from sanic_testing.testing import SanicASGITestClient
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import bindparam
from ulid import ULID

from renku_data_services import errors
from renku_data_services.base_models.core import Slug
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.migrations.core import downgrade_migrations_for_app, get_alembic_config, run_migrations_for_app
from renku_data_services.namespace import orm as ns_schemas
from renku_data_services.users import orm as user_schemas
from renku_data_services.users.models import UserInfo


@pytest.mark.asyncio
async def test_unique_migration_head() -> None:
    cfg = get_alembic_config(name="common")
    script = ScriptDirectory.from_config(cfg)

    heads = script.get_revisions(script.get_heads())
    heads = [h.revision for h in heads]

    assert len(heads) == 1, f"Found more than one revision heads {heads}"


@pytest.mark.asyncio
@pytest.mark.parametrize("downgrade_to, upgrade_to", [("base", "head"), ("fe3b7470d226", "8413f10ef77f")])
async def test_upgrade_downgrade_cycle(
    app_manager_instance: DependencyManager,
    sanic_client_no_migrations: SanicASGITestClient,
    admin_headers: dict,
    admin_user: UserInfo,
    downgrade_to: str,
    upgrade_to: str,
) -> None:
    # Migrate to head and create a project
    run_migrations_for_app("common", upgrade_to)
    await app_manager_instance.kc_user_repo.initialize(app_manager_instance.kc_api)
    await app_manager_instance.group_repo.generate_user_namespaces()
    payload: dict[str, Any] = {
        "name": "test_project",
        "namespace": admin_user.namespace.path.serialize(),
    }
    _, res = await sanic_client_no_migrations.post("/api/data/projects", headers=admin_headers, json=payload)
    assert res.status_code == 201
    project_id = res.json["id"]
    # Migrate/downgrade a few times but end on head
    downgrade_migrations_for_app("common", downgrade_to)
    run_migrations_for_app("common", upgrade_to)
    downgrade_migrations_for_app("common", downgrade_to)
    run_migrations_for_app("common", upgrade_to)
    # Try to make the same project again
    # NOTE: The engine has to be disposed otherwise it caches the postgres types (i.e. enums)
    # from previous migrations and then trying to create a project below fails with the message
    # cache postgres lookup failed for type XXXX.
    await app_manager_instance.config.db.current._async_engine.dispose()
    await app_manager_instance.kc_user_repo.initialize(app_manager_instance.kc_api)
    await app_manager_instance.group_repo.generate_user_namespaces()
    _, res = await sanic_client_no_migrations.post("/api/data/projects", headers=admin_headers, json=payload)
    assert res.status_code in [201, 409], res.json
    if res.status_code == 409:
        # NOTE: This means the project is still in the DB because the down migration was not going
        # far enough to delete the projects table, so we delete the project and recreate it to make sure
        # things are OK.
        _, res = await sanic_client_no_migrations.delete(f"/api/data/projects/{project_id}", headers=admin_headers)
        assert res.status_code == 204, res.json
        _, res = await sanic_client_no_migrations.post("/api/data/projects", headers=admin_headers, json=payload)
        assert res.status_code == 201, res.json


# !IMPORTANT: This test can only be run on v2 of the authz schema
@pytest.mark.skip
@pytest.mark.asyncio
async def test_migration_to_f34b87ddd954(
    sanic_client_no_migrations: SanicASGITestClient,
    app_manager_instance: DependencyManager,
    user_headers: dict,
    admin_headers: dict,
) -> None:
    run_migrations_for_app("common", "d8676f0cde53")
    await app_manager_instance.kc_user_repo.initialize(app_manager_instance.kc_api)
    await app_manager_instance.group_repo.generate_user_namespaces()
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


@pytest.mark.asyncio
async def test_migration_to_1ef98b967767_and_086eb60b42c8(
    app_manager_instance: DependencyManager, admin_user: UserInfo
) -> None:
    """Tests the migration of the session launchers."""
    run_migrations_for_app("common", "b8cbd62e85b9")

    global_env_id = str(ULID())
    custom_launcher_id = str(ULID())
    global_launcher_id = str(ULID())
    project_id = str(ULID())
    async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
        await _generate_user_namespaces(session)
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
    async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
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
    async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
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
    async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
        res = await session.execute(
            sa.text("SELECT * FROM sessions.launchers WHERE id = :id").bindparams(id=custom_launcher_id)
        )
    data = res.all()
    assert len(data) == 1
    custom_launcher = data[0]._mapping
    assert custom_launcher["name"] == "custom"
    assert custom_launcher["project_id"] == project_id
    assert custom_launcher["environment_id"] == custom_env["id"]
    async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
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
    async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
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
    app_manager_instance: DependencyManager,
    sanic_client_no_migrations: SanicASGITestClient,
    admin_headers: dict,
    admin_user: UserInfo,
    tmpdir_factory,
    monkeysession,
) -> None:
    run_migrations_for_app("common", "head")
    envs = await app_manager_instance.session_repo.get_environments()
    assert len(envs) == 2
    assert any(e.name == "Python/Jupyter" for e in envs)
    assert any(e.name == "Rstudio" for e in envs)


@pytest.mark.asyncio
async def test_migration_to_75c83dd9d619(app_manager_instance: DependencyManager, admin_user: UserInfo) -> None:
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

    def find_by_col(data: Sequence[sa.Row[Any]], id_value: Any, id_index: int) -> tuple | None:
        for row in data:
            if row.tuple()[id_index] == id_value:
                return cast(tuple, row.tuple())
        return None

    run_migrations_for_app("common", "450ae3930996")

    async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
        await _generate_user_namespaces(session)
        # Create template project
        project_id = str(ULID())
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
        cloned_project_id = str(ULID())
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
        # Create a clone project that has removed its parent reference
        cloned_project_orphan_id = str(ULID())
        await insert_project(
            session,
            dict(
                id=cloned_project_orphan_id,
                name="cloned_project_orphan",
                created_by_id="some-other-user-id",
                creation_date=datetime.now(UTC),
                visibility="public",
            ),
        )
        # Create unrelated project
        random_project_id = str(ULID())
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
        custom_env_id = str(ULID())
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
        random_env_id = str(ULID())
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
        custom_launcher_id = str(ULID())
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
        custom_launcher_id_cloned = str(ULID())
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
        # A session launcher for the cloned orphaned project
        custom_launcher_id_orphan_cloned = str(ULID())
        await insert_session_launcher(
            session,
            dict(
                id=custom_launcher_id_orphan_cloned,
                name="custom_for_cloned_orphaned_project",
                created_by_id=admin_user.id,
                creation_date=datetime.now(UTC),
                environment_id=custom_env_id,
                project_id=cloned_project_orphan_id,
            ),
        )
        # Create an unrelated session launcher that should be unaffected by the migrations
        random_launcher_id = str(ULID())
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
    async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
        launchers = (await session.execute(sa.text("SELECT id, environment_id, name FROM sessions.launchers"))).all()
        envs = (
            await session.execute(
                sa.text("SELECT id, created_by_id, name FROM sessions.environments WHERE environment_kind = 'CUSTOM'")
            )
        ).all()
    assert len(launchers) == 4
    assert len(envs) == 4
    # Filter the results from the DB
    random_env_row = find_by_col(envs, random_env_id, 0)
    assert random_env_row is not None
    random_launcher_row = find_by_col(launchers, random_launcher_id, 0)
    assert random_launcher_row is not None
    custom_launcher_row = find_by_col(launchers, custom_launcher_id, 0)
    assert custom_launcher_row is not None
    custom_launcher_clone_row = find_by_col(launchers, custom_launcher_id_cloned, 0)
    assert custom_launcher_clone_row is not None
    env1_row = find_by_col(envs, custom_launcher_row[1], 0)
    assert env1_row is not None
    env2_row = find_by_col(envs, custom_launcher_clone_row[1], 0)
    assert env2_row is not None
    # Check that the session launcher for the cloned project is not using the same env as the parent
    assert custom_launcher_row[0] != custom_launcher_clone_row[0]
    assert custom_launcher_row[1] != custom_launcher_clone_row[1]
    assert custom_launcher_row[2] != custom_launcher_clone_row[2]
    # The copied and original env should have different ids and created_by fields
    assert env1_row[0] != env2_row[0]
    assert env1_row[1] != env2_row[1]
    # The copied and the original env have the same name
    assert env1_row[2] == env2_row[2]
    # Check that the random environment is unchanged
    assert random_env_row[0] == random_env_id
    assert random_env_row[1] == admin_user.id
    assert random_env_row[2] == "random env"
    # Check that the orphaned cloned project's environment has been also decoupled
    orphan_launcher_row = find_by_col(launchers, custom_launcher_id_orphan_cloned, 0)
    assert orphan_launcher_row is not None
    orphan_env_row = find_by_col(envs, orphan_launcher_row[1], 0)
    assert orphan_env_row is not None
    assert custom_launcher_row[0] != orphan_launcher_row[0]
    assert custom_launcher_row[1] != orphan_launcher_row[1]
    assert custom_launcher_row[2] != orphan_launcher_row[2]
    assert env1_row[0] != orphan_env_row[0]
    assert env1_row[1] != orphan_env_row[1]
    assert env1_row[2] == orphan_env_row[2]


async def _generate_user_namespaces(session: AsyncSession) -> list[UserInfo]:
    """Generate user namespaces if the user table has data and the namespaces table is empty.

    NOTE: This is copied from GroupRepository to retain the version compatible with db at a fixed point."""

    async def _create_user_namespace_slug(
        session: AsyncSession, user_slug: str, retry_enumerate: int = 0, retry_random: bool = False
    ) -> str:
        """Create a valid namespace slug for a user."""
        nss = await session.scalars(
            sa.select(ns_schemas.NamespaceORM.slug).where(ns_schemas.NamespaceORM.slug.startswith(user_slug))
        )
        nslist = nss.all()
        if user_slug not in nslist:
            return user_slug
        if retry_enumerate:
            for inc in range(1, retry_enumerate + 1):
                slug = f"{user_slug}-{inc}"
                if slug not in nslist:
                    return slug
        if retry_random:
            suffix = "".join([random.choice(string.ascii_lowercase + string.digits) for _ in range(8)])  # nosec B311
            slug = f"{user_slug}-{suffix}"
            if slug not in nslist:
                return slug

        raise errors.ValidationError(message=f"Cannot create generate a unique namespace slug for the user {user_slug}")

    async def _insert_user_namespace(
        session: AsyncSession, user_id: str, user_slug: str, retry_enumerate: int = 0, retry_random: bool = False
    ) -> ns_schemas.NamespaceORM:
        """Insert a new namespace for the user and optionally retry different variations to avoid collisions."""
        namespace = await _create_user_namespace_slug(session, user_slug, retry_enumerate, retry_random)
        slug = Slug.from_name(namespace)
        ns = ns_schemas.NamespaceORM(slug.value, user_id=user_id)
        session.add(ns)
        await session.flush()
        await session.refresh(ns)
        return ns

    # NOTE: lock to make sure another instance of the data service cannot insert/update but can read
    output: list[UserInfo] = []
    await session.execute(sa.text("LOCK TABLE common.namespaces IN EXCLUSIVE MODE"))
    at_least_one_namespace = (await session.execute(sa.select(ns_schemas.NamespaceORM).limit(1))).one_or_none()
    if at_least_one_namespace:
        return []

    res = await session.scalars(sa.select(user_schemas.UserORM))
    for user in res:
        slug = Slug.from_user(user.email, user.first_name, user.last_name, user.keycloak_id)
        ns = await _insert_user_namespace(session, user.keycloak_id, slug.value, retry_enumerate=10, retry_random=True)
        user.namespace = ns
        output.append(user.dump())

    return output


@pytest.mark.asyncio
async def test_migration_to_dcb9648c3c15(app_manager_instance: DependencyManager, admin_user: UserInfo) -> None:
    run_migrations_for_app("common", "042eeb50cd8e")
    async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
        await session.execute(
            sa.text(
                "INSERT into "
                "common.k8s_objects(name, namespace, manifest, deleted, kind, version, cluster, user_id) "
                "VALUES ('name_pod', 'ns', '{}', FALSE, 'pod', 'v1', 'cluster', 'user_id')"
            )
        )
        await session.execute(
            sa.text(
                "INSERT into "
                "common.k8s_objects(name, namespace, manifest, deleted, kind, version, cluster, user_id) "
                "VALUES ('name_js', 'ns', '{}', FALSE, 'jupyterserver', 'amalthea.dev/v1alpha1', 'cluster', 'user_id')"
            )
        )
    run_migrations_for_app("common", "dcb9648c3c15")
    async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
        k8s_objs = (await session.execute(sa.text('SELECT "group", version, kind FROM common.k8s_objects'))).all()
    assert len(k8s_objs) == 2
    assert k8s_objs[0].tuple()[0] is None
    assert k8s_objs[0].tuple()[1] == "v1"
    assert k8s_objs[0].tuple()[2] == "pod"
    assert k8s_objs[1].tuple()[0] == "amalthea.dev"
    assert k8s_objs[1].tuple()[1] == "v1alpha1"
    assert k8s_objs[1].tuple()[2] == "jupyterserver"


@pytest.mark.asyncio
async def test_migration_to_c8061499b966(app_manager_instance: DependencyManager, admin_user: UserInfo) -> None:
    run_migrations_for_app("common", "e117405fed51")
    async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
        await session.execute(
            sa.text(
                "INSERT into "
                "common.k8s_objects(name, namespace, manifest, deleted, kind, version, cluster, user_id) "
                "VALUES ('name_pod', 'ns', '{}', FALSE, 'pod', 'v1', 'renkulab', 'user_id')"
            )
        )
        await session.execute(
            sa.text(
                "INSERT into "
                "common.k8s_objects(name, namespace, manifest, deleted, kind, version, cluster, user_id) "
                "VALUES ('name_js', 'ns', '{}', FALSE, 'jupyterserver', 'amalthea.dev/v1alpha1', 'renkulab', 'user_id')"
            )
        )
    run_migrations_for_app("common", "c8061499b966")
    async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
        k8s_objs = (await session.execute(sa.text("SELECT name, cluster FROM common.k8s_objects"))).all()
    assert len(k8s_objs) == 2
    # Check that the cluster name was changed
    assert k8s_objs[0].tuple()[1] == "0RENK1RENK2RENK3RENK4RENK5"
    assert k8s_objs[1].tuple()[1] == "0RENK1RENK2RENK3RENK4RENK5"
    id = ULID()
    async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
        await session.execute(
            sa.text(
                "INSERT into "
                "common.k8s_objects(name, namespace, manifest, deleted, kind, version, cluster, user_id) "
                f"VALUES ('name_pod', 'ns', '{{}}', FALSE, 'pod', 'v1', '{id}', 'user_id')"
            )
        )
    async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
        k8s_objs = (await session.execute(sa.text("SELECT name, cluster FROM common.k8s_objects"))).all()
    # Check that we can insert another object with the same name, gvk, namespace, but a different cluster
    assert len(k8s_objs) == 3


@pytest.mark.asyncio
async def test_migration_to_04b2a0242f43(app_manager_instance: DependencyManager, admin_user: UserInfo) -> None:
    """Test the migration to deduplicate slugs and add constraints that prevent further duplicates."""

    async def insert_project(session: AsyncSession, name: str) -> ULID:
        proj_id = ULID()
        now = datetime.now()
        await session.execute(
            sa.text(
                "INSERT into "
                "projects.projects(id, name, visibility, created_by_id, creation_date) "
                f"VALUES ('{str(proj_id)}', '{name}', 'public', '{admin_user.id}', '{now.isoformat()}')"
            )
        )
        return proj_id

    async def insert_slug(
        session: AsyncSession,
        slug: str,
        namespace_id: ULID,
        project_id: ULID | None = None,
        data_connector_id: ULID | None = None,
    ) -> None:
        project_id_query = "NULL" if project_id is None else f"'{str(project_id)}'"
        dc_id_query = "NULL" if data_connector_id is None else f"'{str(data_connector_id)}'"
        await session.execute(
            sa.text(
                "INSERT into "
                "common.entity_slugs(slug, namespace_id, project_id, data_connector_id) "
                f"VALUES ('{slug}', '{str(namespace_id)}', {project_id_query}, {dc_id_query} )"
            )
        )

    async def insert_user_namespace(session: AsyncSession, user: UserInfo) -> None:
        await session.execute(
            sa.text(f"INSERT into users.users(keycloak_id) VALUES ('{user.namespace.underlying_resource_id}')")
        )
        await session.execute(
            sa.text(
                "INSERT into "
                "common.namespaces(id, slug, user_id) "
                f"VALUES ('{user.namespace.id}', '{user.namespace.path.serialize()}', "
                f"'{user.namespace.underlying_resource_id}' )"
            )
        )

    async def insert_data_connector(session: AsyncSession, name: str) -> ULID:
        id = ULID()
        now = datetime.now()
        await session.execute(
            sa.text(
                "INSERT into "
                "storage.data_connectors(id, name, visibility, storage_type, configuration, "
                "source_path, target_path, created_by_id, readonly, creation_date) "
                f"VALUES ('{str(id)}', '{name}', 'public', 's3', '{{}}', '/', '/', "
                f"'{admin_user.namespace.underlying_resource_id}', FALSE, '{now.isoformat()}')"
            )
        )
        return id

    run_migrations_for_app("common", "c8061499b966")

    async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
        await insert_user_namespace(session, admin_user)
        # Two projects have duplicate slugs
        p1_id = await insert_project(session, "p1")
        p2_id = await insert_project(session, "p2")
        await insert_slug(session, "p1", admin_user.namespace.id, p1_id)
        await insert_slug(session, "p1", admin_user.namespace.id, p2_id)
        # Two data connectors in the user namespace with duplicate slugs
        dc1_id = await insert_data_connector(session, "dc1")
        dc2_id = await insert_data_connector(session, "dc2")
        await insert_slug(session, "d1", admin_user.namespace.id, None, dc1_id)
        await insert_slug(session, "d1", admin_user.namespace.id, None, dc2_id)
        # Two data connectors in a project namespace with duplicate slugs
        p_for_dc_id = await insert_project(session, "p_for_dc")
        await insert_slug(session, "p_for_dc", admin_user.namespace.id, p_for_dc_id, None)
        p_dc1_id = await insert_data_connector(session, "p_dc1")
        p_dc2_id = await insert_data_connector(session, "p_dc2")
        await insert_slug(session, "dc_in_p", admin_user.namespace.id, p_for_dc_id, p_dc1_id)
        await insert_slug(session, "dc_in_p", admin_user.namespace.id, p_for_dc_id, p_dc2_id)

    # There are duplicated slugs
    async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
        res = await session.execute(sa.text("select distinct slug FROM common.entity_slugs"))
        all_rows = res.all()
        assert len(all_rows) == 4  # 3 duplicates + 1 slug for the project which holds data connectors

    run_migrations_for_app("common", "04b2a0242f43")

    # One project's slug should be renamed and the two slugs are now distinct
    async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
        res = await session.execute(sa.text("select distinct slug FROM common.entity_slugs"))
        all_rows = res.all()
        assert len(all_rows) == 7  # 3 x 2 dedepulicated slugs + 1 for the project which holds data connectors

    # Adding more duplicated slugs should error out
    async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
        p3_id = await insert_project(session, "p3")
        with pytest.raises(IntegrityError):
            await insert_slug(session, "p1", admin_user.namespace.id, p3_id)
    async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
        with pytest.raises(IntegrityError):
            await insert_slug(session, "d1", admin_user.namespace.id, None, dc2_id)
    async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
        with pytest.raises(IntegrityError):
            await insert_slug(session, "dc_in_p", admin_user.namespace.id, p_for_dc_id, p_dc2_id)
