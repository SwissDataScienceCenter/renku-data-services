from datetime import UTC, datetime
from pathlib import PurePosixPath

from ulid import ULID

from renku_data_services.authz.models import Visibility
from renku_data_services.base_models.core import NamespacePath
from renku_data_services.namespace.models import UserNamespace
from renku_data_services.notebooks.crs import Affinity
from renku_data_services.project.models import Project
from renku_data_services.renku_apps.core import generate_app_name
from renku_data_services.renku_apps.k8s_client import RenkuAppsK8sClient
from renku_data_services.session.models import (
    Environment,
    EnvironmentImageSource,
    EnvironmentKind,
    LauncherType,
    Member,
    SessionLauncher,
)
from test.utils import FakeK8sClusterClientsPool


def _project() -> Project:
    return Project(
        id=ULID(),
        name="My project",
        slug="my-project",
        visibility=Visibility.PUBLIC,
        created_by="user-1",
        namespace=UserNamespace(
            id=ULID(),
            created_by="user-1",
            path=NamespacePath.from_strings("user-1"),
            underlying_resource_id="user-1",
        ),
        secrets_mount_directory=PurePosixPath("/secrets"),
    )


def _launcher(project_id: ULID) -> SessionLauncher:
    return SessionLauncher(
        id=ULID(),
        project_id=project_id,
        name="My app",
        description=None,
        resource_class_id=None,
        disk_storage=None,
        env_variables=None,
        launcher_type=LauncherType.app,
        creation_date=datetime.now(UTC),
        created_by=Member(id="user-1"),
        environment=Environment(
            id=ULID(),
            name="app environment",
            container_image="nginx:1.29",
            default_url="/",
            port=8080,
            # Set so that the working directory is not read from the image registry over the network.
            working_directory=PurePosixPath("/app"),
            mount_directory=None,
            uid=1000,
            gid=1000,
            environment_kind=EnvironmentKind.CUSTOM,
            environment_image_source=EnvironmentImageSource.image,
            creation_date=datetime.now(UTC),
            created_by=Member(id="user-1"),
            build_parameters=None,
            build_parameters_id=None,
        ),
    )


async def test_app_deployment_round_trip() -> None:
    client = RenkuAppsK8sClient(
        client=FakeK8sClusterClientsPool(namespace="renku"),
        cluster_repo=None,
        storage_class="csi-rclone",
        default_affinity=Affinity(),
        default_tolerations=[],
    )
    project = _project()
    launcher = _launcher(project.id)

    created = await client.create_app_deployment(launcher, None, project, [])

    assert created.name == generate_app_name(project.slug, launcher.id)
    assert created.launcher_id == launcher.id
    assert created.project_id == project.id
    assert created.image == launcher.environment.container_image

    assert await client.get_app_deployment(created.name) == created
    assert await client.get_app_deployment_for_launcher(launcher.id) == created
    assert [state.name async for state in client.list_app_deployments(project.id)] == [created.name]
    assert [state async for state in client.list_app_deployments(ULID())] == []
    assert await client.get_app_deployment_for_launcher(ULID()) is None

    await client.delete_app_deployment(created.name)

    assert await client.get_app_deployment(created.name) is None
    assert [state async for state in client.list_app_deployments(project.id)] == []
