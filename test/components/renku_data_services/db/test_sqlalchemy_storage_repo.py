from test.components.renku_data_services.storage_models.hypothesis import (
    a_path,
    azure_configuration,
    s3_configuration,
    storage_strat,
)
from test.utils import create_storage
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from renku_data_services import errors
from renku_data_services.storage_adapters import StorageRepository


@given(storage=storage_strat())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@pytest.mark.asyncio
async def test_storage_insert_get(storage: dict[str, Any], storage_repo: StorageRepository):
    try:
        await create_storage(storage, storage_repo)
    except (ValidationError, errors.ValidationError):
        pass


@given(storage=storage_strat(), new_source_path=a_path, new_target_path=a_path)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@pytest.mark.asyncio
async def test_storage_update_path(
    storage: dict[str, Any], new_source_path: str, new_target_path: str, storage_repo: StorageRepository
):
    try:
        inserted_storage = await create_storage(storage, storage_repo)
        assert inserted_storage.storage_id is not None

        updated_storage = await storage_repo.update_storage(
            storage_id=inserted_storage.storage_id, source_path=new_source_path, target_path=new_target_path
        )
    except (ValidationError, errors.ValidationError):
        pass
    else:
        assert updated_storage.source_path == new_source_path
        assert updated_storage.target_path == new_target_path


@given(storage=storage_strat(), new_config=st.one_of(s3_configuration(), azure_configuration()))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@pytest.mark.asyncio
async def test_storage_update_config(
    storage: dict[str, Any], new_config: dict[str, Any], storage_repo: StorageRepository
):
    try:
        inserted_storage = await create_storage(storage, storage_repo)
        assert inserted_storage.storage_id is not None

        updated_storage = await storage_repo.update_storage(
            storage_id=inserted_storage.storage_id, configuration=new_config
        )
    except (ValidationError, errors.ValidationError):
        pass
    else:
        assert updated_storage.configuration.model_dump() == new_config


@given(storage=storage_strat())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@pytest.mark.asyncio
async def test_storage_delete(storage: dict[str, Any], storage_repo: StorageRepository):
    try:
        inserted_storage = await create_storage(storage, storage_repo)
        assert inserted_storage.storage_id is not None
        await storage_repo.delete_storage(storage_id=inserted_storage.storage_id)
        storages = await storage_repo.get_storage(project_id=inserted_storage.project_id)
        assert len(storages) == 0
    except (ValidationError, errors.ValidationError):
        pass
