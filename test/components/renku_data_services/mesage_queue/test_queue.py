"""Test for the message queue."""

import asyncio
import contextlib

import pytest

from renku_data_services.message_queue.avro_models.io.renku.events.v1.project_removed import ProjectRemoved
from renku_data_services.message_queue.redis_queue import dispatch_message
from renku_data_services.utils.core import with_db_transaction


@pytest.mark.asyncio
async def test_queue_resend(app_config, monkeypatch):
    """Test that resending failed requests works."""

    class FakeException(Exception):
        pass

    def raise_fake_exception(*_, **__):
        raise FakeException()

    send_msg = app_config.message_queue.send_message
    monkeypatch.setattr(app_config.message_queue, "send_message", raise_fake_exception)

    def proj_del_message(result, some_arg) -> ProjectRemoved:
        return ProjectRemoved(id=result)

    class FakeRepo:
        session_maker = app_config.db.async_session_maker
        event_repo = app_config.event_repo
        message_queue = app_config.message_queue

        @with_db_transaction
        @dispatch_message(proj_del_message)
        async def fake_db_method(self, session, some_arg):
            return "abcdefg"

    fakerepo = FakeRepo()
    with contextlib.suppress(FakeException):
        await fakerepo.fake_db_method("test")

    events = await app_config.redis.redis_connection.xrange("project.removed")
    assert len(events) == 0
    pending_events = await app_config.event_repo.get_pending_events()
    assert len(pending_events) == 1

    monkeypatch.setattr(app_config.message_queue, "send_message", send_msg)

    await app_config.event_repo.send_pending_events()

    events = await app_config.redis.redis_connection.xrange("project.removed")
    assert len(events) == 0
    pending_events = await app_config.event_repo.get_pending_events()
    assert len(pending_events) == 1

    # make sure event is not immeciately resent
    await app_config.event_repo.send_pending_events()

    events = await app_config.redis.redis_connection.xrange("project.removed")
    assert len(events) == 0
    pending_events = await app_config.event_repo.get_pending_events()
    assert len(pending_events) == 1

    # ensure it is resent if older than 5 seconds
    await asyncio.sleep(6)
    await app_config.event_repo.send_pending_events()

    events = await app_config.redis.redis_connection.xrange("project.removed")
    assert len(events) == 1
    pending_events = await app_config.event_repo.get_pending_events()
    assert len(pending_events) == 0
