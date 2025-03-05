import random
import string

import pytest

from renku_data_services.solr import entity_schema
from renku_data_services.solr.solr_client import DefaultSolrAdminClient, SolrClientConfig
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


@pytest.mark.asyncio
async def test_creating_schema_in_new_core(solr_config):
    random_name = "".join(random.choices(string.ascii_lowercase + string.digits, k=9))
    async with DefaultSolrAdminClient(solr_config) as client:
        res = await client.create(random_name)
        assert res is None

    next_cfg = SolrClientConfig(base_url=solr_config.base_url, core=random_name, user=solr_config.user)

    migrator = SchemaMigrator(next_cfg)
    migrations = entity_schema.all_migrations.copy()
    result = await migrator.migrate(migrations)
    migrations.sort(key=lambda e: e.version)
    last = migrations[-1]
    assert result.end_version == last.version
    assert result.migrations_run == len(migrations)
    assert result.migrations_skipped == 0
    assert result.requires_reindex
