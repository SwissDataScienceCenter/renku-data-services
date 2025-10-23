"""Tests for the db module."""

import uuid

import pytest

from renku_data_services.authz.models import Visibility
from renku_data_services.base_models.core import AuthenticatedAPIUser
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.data_connectors.models import CloudStorageCore, UnsavedDataConnector
from renku_data_services.errors import MissingResourceError
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.project.models import UnsavedProject


@pytest.mark.asyncio
async def test_remove_project_removes_data_connector(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")

    user_repo = app_manager_instance.kc_user_repo
    proj_repo = app_manager_instance.project_repo
    dc_repo = app_manager_instance.data_connector_repo

    user = AuthenticatedAPIUser(id=str(uuid.uuid4()), access_token="abc", first_name="Huhu")
    u = await user_repo.get_or_create_user(user, user.id)
    assert u

    proj1 = await proj_repo.insert_project(
        user,
        UnsavedProject(
            namespace=u.namespace.path.first.value,
            name=f"proj of user {u.first_name}",
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

    deleted_proj = await proj_repo.delete_project(user, proj1.id)
    assert deleted_proj
    assert deleted_proj.id == proj1.id
    assert deleted_proj.data_connectors == [dc_in_proj.id]

    with pytest.raises(MissingResourceError):
        await proj_repo.get_project(user, proj1.id)

    with pytest.raises(MissingResourceError):
        await dc_repo.get_data_connector(user, dc_in_proj.id)
