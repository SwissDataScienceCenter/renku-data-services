"""Business logic for searching."""

import logging
from datetime import datetime

from renku_data_services.base_models import APIUser
from renku_data_services.message_queue.db import ReprovisioningRepository
from renku_data_services.message_queue.models import Reprovisioning
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.project.db import ProjectRepository
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.users.db import UserRepo


async def reprovision(
    requested_by: APIUser,
    reprovisioning: Reprovisioning,
    search_updates_repo: SearchUpdatesRepo,
    reprovisioning_repo: ReprovisioningRepository,
    user_repo: UserRepo,
    group_repo: GroupRepository,
    project_repo: ProjectRepository,
) -> None:
    """Initiates reprovisioning by inserting documents into the staging table."""

    def log_counter(c: int) -> None:
        if c % 50 == 0:
            logging.info(f"Inserted {c}. entities into staging table...")

    try:
        logging.info(f"Starting reprovisioning with ID {reprovisioning.id}")
        started = datetime.now()
        await search_updates_repo.clear_all()
        all_users = user_repo.get_all_users(requested_by=requested_by)
        counter = 0
        async for user_entity in all_users:
            await search_updates_repo.insert(user_entity, started)
            counter += 1
            log_counter(counter)

        all_groups = group_repo.get_all_groups(requested_by=requested_by)
        async for group_entity in all_groups:
            await search_updates_repo.insert(group_entity, started)
            counter += 1
            log_counter(counter)

        all_projects = project_repo.get_all_projects(requested_by=requested_by)
        async for project_entity in all_projects:
            await search_updates_repo.insert(project_entity, started)
            counter += 1
            log_counter(counter)

        logging.info(f"Inserted {counter} entities into the staging table.")

        ## TODO error handling. skip or fail?
    finally:
        await reprovisioning_repo.stop()
