"""Tests for reprovision module."""

import pytest

from renku_data_services.authz.authz import Authz
from renku_data_services.data_connectors.db import DataConnectorRepository
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.project.db import ProjectRepository
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.search.reprovision import SearchReprovision


@pytest.mark.asyncio
def test_get_data_connectors(app_config_instance) -> None:
    run_migrations_for_app("common")
    repro = SearchReprovision(
        search_updates_repo=SearchUpdatesRepo(app_config_instance.db_async_session_maker),
        reprovisioning_repo=None,
        solr_config=None,
        user_repo=None,
        group_repo=None,
        project_repo=None,
        data_connector_repo=DataConnectorRepository(
            app_config_instance.db_async_session_maker, Authz(app_config_instance.authz_config)
        ),
    )
    print(f"repro: {repro}")
