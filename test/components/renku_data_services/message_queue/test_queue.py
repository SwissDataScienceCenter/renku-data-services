"""Test for the message queue."""

import pytest

from renku_data_services.authz.models import Visibility
from renku_data_services.base_models.core import NamespacePath
from renku_data_services.message_queue.avro_models.io.renku.events.v2.project_removed import ProjectRemoved
from renku_data_services.message_queue.converters import QUEUE_NAME
from renku_data_services.message_queue.redis_queue import dispatch_message
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.namespace.models import UserNamespace
from renku_data_services.project.models import Project
from renku_data_services.utils.core import with_db_transaction


@pytest.mark.asyncio
async def test_queue_send(app_manager_instance) -> None:
    """Test that sending messages works."""
    run_migrations_for_app("common")

    class FakeRepo:
        session_maker = app_manager_instance.config.db.async_session_maker
        event_repo = app_manager_instance.event_repo
        message_queue = app_manager_instance.message_queue

        @with_db_transaction
        @dispatch_message(ProjectRemoved)
        async def fake_db_method(self, *, session, some_arg):
            return Project(
                id="sample-id-1",
                name="name",
                slug="slug",
                namespace=UserNamespace(
                    id="namespace",
                    created_by="some-user",
                    underlying_resource_id="some-user",
                    path=NamespacePath.from_strings("namespace"),
                ),
                visibility=Visibility.PRIVATE,
                created_by="some-user",
            )

    fakerepo = FakeRepo()
    await fakerepo.fake_db_method(some_arg="test")

    events = await app_manager_instance.config.redis.redis_connection.xrange(QUEUE_NAME)
    assert len(events) == 0
    pending_events = await app_manager_instance.event_repo.get_pending_events()
    assert len(pending_events) == 1

    await app_manager_instance.event_repo.send_pending_events()

    events = await app_manager_instance.config.redis.redis_connection.xrange(QUEUE_NAME)
    assert len(events) == 1
    pending_events = await app_manager_instance.event_repo.get_pending_events()
    assert len(pending_events) == 0

    await app_manager_instance.event_repo.send_pending_events()

    events = await app_manager_instance.config.redis.redis_connection.xrange(QUEUE_NAME)
    assert len(events) == 1
    pending_events = await app_manager_instance.event_repo.get_pending_events()
    assert len(pending_events) == 0
