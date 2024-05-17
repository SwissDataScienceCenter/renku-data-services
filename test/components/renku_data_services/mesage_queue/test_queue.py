"""Test for the message queue."""

import pytest

from renku_data_services.authz.models import Visibility
from renku_data_services.message_queue.avro_models.io.renku.events.v1.project_removed import ProjectRemoved
from renku_data_services.message_queue.redis_queue import dispatch_message
from renku_data_services.project.models import Project
from renku_data_services.utils.core import with_db_transaction


@pytest.mark.asyncio
async def test_queue_send(app_config, monkeypatch):
    """Test that sending messages works."""

    class FakeRepo:
        session_maker = app_config.db.async_session_maker
        event_repo = app_config.event_repo
        message_queue = app_config.message_queue

        @with_db_transaction
        @dispatch_message(ProjectRemoved)
        async def fake_db_method(self, session, some_arg):
            return Project(
                id="sample-id-1",
                name="name",
                slug="slug",
                namespace="name",
                visibility=Visibility.PRIVATE,
                created_by="some-user",
            )

    fakerepo = FakeRepo()
    await fakerepo.fake_db_method("test")

    events = await app_config.redis.redis_connection.xrange("project.removed")
    assert len(events) == 0
    pending_events = await app_config.event_repo.get_pending_events()
    assert len(pending_events) == 1

    await app_config.event_repo.send_pending_events()

    events = await app_config.redis.redis_connection.xrange("project.removed")
    assert len(events) == 1
    pending_events = await app_config.event_repo.get_pending_events()
    assert len(pending_events) == 0

    # ensure it is resent if older than 5 seconds
    await app_config.event_repo.send_pending_events()

    events = await app_config.redis.redis_connection.xrange("project.removed")
    assert len(events) == 1
    pending_events = await app_config.event_repo.get_pending_events()
    assert len(pending_events) == 0
