"""Business logic for message queue and events."""

from collections.abc import Callable

from sanic.log import logger
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services.authz.authz import Authz, ResourceType
from renku_data_services.base_models import APIUser
from renku_data_services.message_queue.avro_models.io.renku.events import v2
from renku_data_services.message_queue.converters import (
    EventConverter,
    make_event,
    make_group_member_added_event,
    make_project_member_added_event,
)
from renku_data_services.message_queue.db import EventRepository, ReprovisioningRepository
from renku_data_services.message_queue.models import Reprovisioning
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.project.db import ProjectRepository
from renku_data_services.users.db import UserRepo


async def reprovision(
    session_maker: Callable[..., AsyncSession],
    requested_by: APIUser,
    reprovisioning: Reprovisioning,
    reprovisioning_repo: ReprovisioningRepository,
    event_repo: EventRepository,
    user_repo: UserRepo,
    group_repo: GroupRepository,
    project_repo: ProjectRepository,
    authz: Authz,
) -> None:
    """Create and send various data service events required for reprovisioning the message queue."""
    logger.info(f"Starting reprovisioning with ID {reprovisioning.id}")

    try:
        async with session_maker() as session, session.begin():
            start_event = make_event(
                message_type="reprovisioning.started", payload=v2.ReprovisioningStarted(id=str(reprovisioning.id))
            )
            await event_repo.store_event(session, start_event)

            logger.info("Reprovisioning users")
            all_users = await user_repo.get_users(requested_by=requested_by)
            for user in all_users:
                user_event = EventConverter.to_events(user, event_type=v2.UserAdded)
                await event_repo.store_event(session, user_event[0])

            logger.info("Reprovisioning groups")
            all_groups = group_repo.get_all_groups(requested_by=requested_by)
            async for group in all_groups:
                group_event = EventConverter.to_events(group, event_type=v2.GroupAdded)
                await event_repo.store_event(session, group_event[0])

            logger.info("Reprovisioning group members")
            all_groups_members = authz.get_all_members(ResourceType.group)
            async for group_member in all_groups_members:
                group_member_event = make_group_member_added_event(member=group_member)
                await event_repo.store_event(session, group_member_event)

            logger.info("Reprovisioning projects")
            all_projects = project_repo.get_all_projects(requested_by=requested_by)
            async for project in all_projects:
                project_event = EventConverter.to_events(project, event_type=v2.ProjectCreated)
                await event_repo.store_event(session, project_event[0])

            logger.info("Reprovisioning project members")
            all_projects_members = authz.get_all_members(ResourceType.project)
            async for project_member in all_projects_members:
                project_member_event = make_project_member_added_event(member=project_member)
                await event_repo.store_event(session, project_member_event)

            finish_event = make_event(
                message_type="reprovisioning.finished", payload=v2.ReprovisioningFinished(id=str(reprovisioning.id))
            )
            await event_repo.store_event(session, finish_event)

            logger.info(f"Trying to commit reprovisioning with ID {reprovisioning.id}")
    except Exception as e:
        logger.exception(f"An error occurred during reprovisioning with ID {reprovisioning.id}: {e}")
    else:
        logger.info(f"Reprovisioning with ID {reprovisioning.id} is successfully finished")
    finally:
        await reprovisioning_repo.stop()
