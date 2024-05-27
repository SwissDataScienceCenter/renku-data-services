"""Test for the message queue."""

import asyncio
import contextlib

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services.authz.models import Visibility
from renku_data_services.message_queue.avro_models.io.renku.events.v2.project_removed import ProjectRemoved
from renku_data_services.message_queue.redis_queue import dispatch_message
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.namespace.models import Namespace, NamespaceKind
from renku_data_services.project.models import Project
from renku_data_services.utils.core import with_db_transaction


@pytest.mark.asyncio
async def test_queue_resend(app_config, monkeypatch) -> None:
    """Test that resending failed requests works."""

    run_migrations_for_app("common")

    class FakeException(Exception):
        pass

    def raise_fake_exception(*_, **__):
        raise FakeException()

    send_msg = app_config.message_queue.send_message
    monkeypatch.setattr(app_config.message_queue, "send_message", raise_fake_exception)

    class FakeRepo:
        session_maker = app_config.db.async_session_maker
        event_repo = app_config.event_repo
        message_queue = app_config.message_queue

        @with_db_transaction
        @dispatch_message(ProjectRemoved)
        async def fake_db_method(self, some_arg, *, session: AsyncSession | None = None):
            return Project(
                id="sample-id-1",
                name="name",
                slug="slug",
                namespace=Namespace("namespace", "namespace", NamespaceKind.user),
                visibility=Visibility.PRIVATE,
                created_by="some-user",
            )

    fakerepo = FakeRepo()
    with contextlib.suppress(FakeException):
        await fakerepo.fake_db_method("test")

    events = await app_config.redis.redis_connection.xrange("project.removed")
    assert len(events) == 0
    pending_events = await app_config.event_repo._get_pending_events()
    assert len(pending_events) == 1

    monkeypatch.setattr(app_config.message_queue, "send_message", send_msg)

    await app_config.event_repo.send_pending_events()

    events = await app_config.redis.redis_connection.xrange("project.removed")
    assert len(events) == 0
    pending_events = await app_config.event_repo._get_pending_events()
    assert len(pending_events) == 1

    # make sure event is not immeciately resent
    await app_config.event_repo.send_pending_events()

    events = await app_config.redis.redis_connection.xrange("project.removed")
    assert len(events) == 0
    pending_events = await app_config.event_repo._get_pending_events()
    assert len(pending_events) == 1

    # ensure it is resent if older than 5 seconds
    await asyncio.sleep(6)
    await app_config.event_repo.send_pending_events()

    events = await app_config.redis.redis_connection.xrange("project.removed")
    assert len(events) == 1
    pending_events = await app_config.event_repo._get_pending_events()
    assert len(pending_events) == 0
