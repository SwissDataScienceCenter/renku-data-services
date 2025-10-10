"""Tests for the SearchUpdatesORM."""

from datetime import datetime

import pytest
from sqlalchemy import select

from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.search.orm import SearchUpdatesORM


@pytest.mark.asyncio
async def test_insert_and_retrieve(app_manager_instance):
    run_migrations_for_app("common")
    async with app_manager_instance.config.db.async_session_maker() as session:
        async with session.begin():
            row = SearchUpdatesORM(entity_id="user47", entity_type="User", created_at=datetime.now(), payload={})
            session.add_all([row])
            await session.commit()

        await session.begin()
        res = await session.scalars(select(SearchUpdatesORM).order_by(SearchUpdatesORM.id))
        record = res.one()
        assert row.entity_id == record.entity_id
        assert len(str(record.id)) > 0
