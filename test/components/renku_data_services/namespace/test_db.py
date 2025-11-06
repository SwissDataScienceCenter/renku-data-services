"""Tests for the db module."""

import uuid

import pytest

from renku_data_services.authz.models import Visibility
from renku_data_services.base_models.core import AuthenticatedAPIUser
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.data_connectors.models import CloudStorageCore, UnsavedDataConnector
from renku_data_services.errors import MissingResourceError
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.namespace.models import UnsavedGroup
from renku_data_services.project.models import UnsavedProject


@pytest.mark.asyncio
async def test_remove_group_removes_containing_entities(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")

    user_repo = app_manager_instance.kc_user_repo
    group_repo = app_manager_instance.group_repo
    proj_repo = app_manager_instance.project_repo
    dc_repo = app_manager_instance.data_connector_repo

    user = AuthenticatedAPIUser(id=str(uuid.uuid4()), access_token="abc", first_name="Huhu")
    u = await user_repo.get_or_create_user(user, user.id)
    assert u

    group = await group_repo.insert_group(user, UnsavedGroup(slug="grr1", name="Group Grr"))

    proju = await proj_repo.insert_project(
        user,
        UnsavedProject(
            namespace=u.namespace.path.first.value,
            name=f"proj of user {u.first_name}",
            slug="proj-user",
            visibility=Visibility.PUBLIC,
            created_by=user.id,
        ),
    )
    proj1 = await proj_repo.insert_project(
        user,
        UnsavedProject(
            namespace=group.slug,
            name=f"proj of group {group.name}",
            slug="proj-group-1",
            visibility=Visibility.PUBLIC,
            created_by=user.id,
        ),
    )
    dc_in_proj = await dc_repo.insert_namespaced_data_connector(
        user,
        UnsavedDataConnector(
            name="dc 1",
            slug="dc1",
            visibility=Visibility.PUBLIC,
            created_by=user.id,
            namespace=proj1.path,
            storage=CloudStorageCore(
                storage_type="csc", configuration={}, source_path="", target_path="", readonly=True
            ),
        ),
    )
    dc_in_group = await dc_repo.insert_namespaced_data_connector(
        user,
        UnsavedDataConnector(
            name="dc 1",
            slug="dc1",
            visibility=Visibility.PUBLIC,
            created_by=user.id,
            namespace=group.path,
            storage=CloudStorageCore(
                storage_type="csc", configuration={}, source_path="", target_path="", readonly=True
            ),
        ),
    )

    deleted_group = await group_repo.delete_group(user, group.path.first)
    assert deleted_group
    assert deleted_group.id == group.id
    assert deleted_group.data_connectors == [dc_in_proj.id, dc_in_group.id]
    assert len(deleted_group.projects) == 1
    assert deleted_group.projects == [proj1.id]

    # this must still exist
    await proj_repo.get_project(user, proju.id)

    with pytest.raises(MissingResourceError):
        await group_repo.get_group(user, group.path.first)

    with pytest.raises(MissingResourceError):
        await proj_repo.get_project(user, proj1.id)

    with pytest.raises(MissingResourceError):
        await dc_repo.get_data_connector(user, dc_in_proj.id)
