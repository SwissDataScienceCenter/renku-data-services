"""Tests for resource data."""

import pytest
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.migrations.core import run_migrations_for_app


@pytest.mark.asyncio
async def test_record_resource_requests(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")
