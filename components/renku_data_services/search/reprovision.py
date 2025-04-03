"""Code for reprovisioning the search index."""

import asyncio
from asyncio import Task
from datetime import datetime

from sanic.log import logger

from renku_data_services.base_models.core import APIUser
from renku_data_services.message_queue.db import ReprovisioningRepository
from renku_data_services.message_queue.models import Reprovisioning
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.project.db import ProjectRepository
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.solr.solr_client import DefaultSolrClient, SolrClientConfig
from renku_data_services.users.db import UserRepo


class SearchReprovision:
    """Encapsulates routines to reprovision the index."""

    def __init__(
        self,
        search_updates_repo: SearchUpdatesRepo,
        reprovisioning_repo: ReprovisioningRepository,
        solr_config: SolrClientConfig,
        user_repo: UserRepo,
        group_repo: GroupRepository,
        project_repo: ProjectRepository,
    ) -> None:
        self.search_updates_repo = search_updates_repo
        self.reprovisioning_repo = reprovisioning_repo
        self.solr_config = solr_config
        self.user_repo = user_repo
        self.group_repo = group_repo
        self.project_repo = project_repo

    async def reprovision_task(self, requested_by: APIUser) -> Task:
        """Creates a task that initiates reprovisioning."""
        reprovision = await self.reprovisioning_repo.start()
        task = asyncio.create_task(
            self.init_reprovision(requested_by, reprovision), name=f"search-reprovision-{reprovision.id}"
        )
        return task

    async def run_reprovision(self, requested_by: APIUser) -> None:
        """Start a reprovisioning if not already running."""
        reprovision = await self.reprovisioning_repo.start()
        await self.init_reprovision(requested_by, reprovision)

    async def acquire_reprovsion(self) -> Reprovisioning:
        """Acquire a reprovisioning slot. Throws if already taken."""
        return await self.reprovisioning_repo.start()

    async def kill_reprovision_lock(self) -> None:
        """Removes an existing reprovisioning lock."""
        return await self.reprovisioning_repo.stop()

    async def get_current_reprovision(self) -> Reprovisioning | None:
        """Return the current reprovisioning lock."""
        return await self.reprovisioning_repo.get_active_reprovisioning()

    async def init_reprovision(self, requested_by: APIUser, reprovisioning: Reprovisioning) -> None:
        """Initiates reprovisioning by inserting documents into the staging table."""

        def log_counter(c: int) -> None:
            if c % 50 == 0:
                logger.info(f"Inserted {c}. entities into staging table...")

        try:
            logger.info(f"Starting reprovisioning with ID {reprovisioning.id}")
            started = datetime.now()
            await self.search_updates_repo.clear_all()
            async with DefaultSolrClient(self.solr_config) as client:
                await client.delete("_type:*")
            counter = 0
            all_users = self.user_repo.get_all_users(requested_by=requested_by)
            async for user_entity in all_users:
                await self.search_updates_repo.insert(user_entity, started)
                counter += 1
                log_counter(counter)

            all_groups = self.group_repo.get_all_groups(requested_by=requested_by)
            async for group_entity in all_groups:
                await self.search_updates_repo.insert(group_entity, started)
                counter += 1
                log_counter(counter)

            all_projects = self.project_repo.get_all_projects(requested_by=requested_by)
            async for project_entity in all_projects:
                await self.search_updates_repo.insert(project_entity, started)
                counter += 1
                log_counter(counter)

            logger.info(f"Inserted {counter} entities into the staging table.")

        except Exception as e:
            logger.error("Error while reprovisioning entities!", exc_info=e)
            ## TODO error handling. skip or fail?
        finally:
            await self.reprovisioning_repo.stop()
