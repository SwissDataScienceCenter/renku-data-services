"""Tests for the core functions."""

import pytest
import sqlalchemy as sa
from ulid import ULID

import renku_data_services.search.core as core
from renku_data_services.base_models.core import NamespacePath
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.namespace.models import UserNamespace
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.search.orm import RecordState, SearchUpdatesORM
from renku_data_services.solr.entity_documents import User
from renku_data_services.solr.solr_client import DefaultSolrClient, SolrClientConfig, SolrQuery
from renku_data_services.users.models import UserInfo

user_namespace = UserNamespace(
    id=ULID(),
    created_by="userid_2",
    underlying_resource_id=str(ULID()),
    path=NamespacePath.from_strings("user"),
)


@pytest.mark.asyncio
async def test_update_solr(app_manager_instance, solr_search):
    run_migrations_for_app("common")
    repo = SearchUpdatesRepo(app_manager_instance.config.db.async_session_maker)

    user = UserInfo(id="user123", first_name="Tadej", last_name="Pogacar", namespace=user_namespace)
    await repo.upsert(user, started_at=None)

    user = UserInfo(id="user234", first_name="Greg", last_name="Lemond", namespace=user_namespace)
    await repo.upsert(user, started_at=None)

    async with DefaultSolrClient(solr_search) as client:
        before = await client.query(SolrQuery.query_all_fields("_type:*"))
        assert len(before.response.docs) == 0

        await core.update_solr(repo, client, 10)

        result = await client.query(SolrQuery.query_all_fields("_type:*"))
        assert len(result.response.docs) == 2
        entities = await repo.select_next(10)
        assert len(entities) == 0

        user = UserInfo(id="user234", first_name="Greg", last_name="Larrsson", namespace=user_namespace)
        await repo.upsert(user, started_at=None)
        await core.update_solr(repo, client, 10)
        entities = await repo.select_next(10)
        assert len(entities) == 0
        doc = await client.get("user234")
        users = doc.response.read_to(User.from_dict)
        assert users[0].lastName == "Larrsson"


@pytest.mark.asyncio
async def test_update_no_solr(app_manager_instance):
    run_migrations_for_app("common")
    repo = SearchUpdatesRepo(app_manager_instance.config.db.async_session_maker)

    user = UserInfo(id="user123", first_name="Tadej", last_name="Pogacar", namespace=user_namespace)
    await repo.upsert(user, started_at=None)

    user = UserInfo(id="user234", first_name="Greg", last_name="Lemond", namespace=user_namespace)
    await repo.upsert(user, started_at=None)

    solr_config = SolrClientConfig(base_url="", core="_none_")

    async with DefaultSolrClient(solr_config) as client:
        try:
            await core.update_solr(repo, client, 10)
            raise Exception("Not expected to succeed")
        except Exception as _:
            entities = await repo.select_next(10)
            assert len(entities) == 0
            async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
                res = await session.scalars(sa.select(SearchUpdatesORM).order_by(SearchUpdatesORM.id))
                states = [s.state for s in res.all()]
                assert states == [RecordState.Failed, RecordState.Failed]
