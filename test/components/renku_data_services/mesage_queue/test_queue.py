"""Test for the message queue."""

from datetime import datetime

import pytest

from renku_data_services.message_queue.avro_models.io.renku.events.v1.visibility import Visibility


@pytest.mark.asyncio
async def test_queue_resend(app_config):
    """Test that resending failed requests works."""
    num_events = len(await app_config.redis.redis_connection.xrange("project.created"))

    class FakeException(Exception):
        pass

    try:
        async with app_config.message_queue.project_created_message(
            name="project",
            slug="project",
            visibility=Visibility.PUBLIC,
            id="abcdefg",
            repositories=[],
            description="test",
            creation_date=datetime.utcnow(),
            created_by="user1",
        ) as message:
            # here we'd normally do changes to the database
            # and the context manager would send the message and clean up toward the end
            await message.persist(app_config.event_repo)
            raise FakeException("Dummy exception")
    except FakeException:
        pass

    events = await app_config.redis.redis_connection.xrange("project.created")
    assert len(events) == num_events
    pending_events = await app_config.event_repo.get_pending_events()
    assert len(pending_events) == 1

    await app_config.event_repo.send_pending_events()

    events = await app_config.redis.redis_connection.xrange("project.created")
    assert len(events) == num_events + 1
    pending_events = await app_config.event_repo.get_pending_events()
    assert len(pending_events) == 0
