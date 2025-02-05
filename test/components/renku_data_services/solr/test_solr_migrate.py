import pytest

from renku_data_services.solr import entity_schema
from renku_data_services.solr.solr_migrate import SchemaMigrator


@pytest.mark.asyncio
async def test_creating_schema(solr_config):
    migrator = SchemaMigrator(solr_config)
    migrations = entity_schema.all_migrations.copy()
    result = await migrator.migrate(migrations)
    migrations.sort(key=lambda e: e.version)
    last = migrations[-1]
    assert result.end_version == last.version
    assert result.migrations_run == len(migrations)
    assert result.migrations_skipped == 0
    assert result.requires_reindex
