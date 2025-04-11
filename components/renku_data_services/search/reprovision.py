"""Code for reprovisioning the search index."""

from collections.abc import AsyncGenerator, Callable
from datetime import datetime

from sanic.log import logger

from renku_data_services.base_models.core import APIUser
from renku_data_services.data_connectors.db import DataConnectorRepository
from renku_data_services.data_connectors.models import DataConnector
from renku_data_services.message_queue.db import ReprovisioningRepository
from renku_data_services.message_queue.models import Reprovisioning
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.namespace.models import Group
from renku_data_services.project.db import ProjectRepository
from renku_data_services.project.models import Project
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.solr.solr_client import DefaultSolrClient, SolrClientConfig
from renku_data_services.users.db import UserRepo
from renku_data_services.users.models import UserInfo


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
        data_connector_repo: DataConnectorRepository,
    ) -> None:
        self._search_updates_repo = search_updates_repo
        self._reprovisioning_repo = reprovisioning_repo
        self._solr_config = solr_config
        self._user_repo = user_repo
        self._group_repo = group_repo
        self._project_repo = project_repo
        self._data_connector_repo = data_connector_repo

    async def run_reprovision(self, requested_by: APIUser) -> None:
        """Start a reprovisioning if not already running."""
        reprovision = await self._reprovisioning_repo.start()
        await self.init_reprovision(requested_by, reprovision)

    async def acquire_reprovision(self) -> Reprovisioning:
        """Acquire a reprovisioning slot. Throws if already taken."""
        return await self._reprovisioning_repo.start()

    async def kill_reprovision_lock(self) -> None:
        """Removes an existing reprovisioning lock."""
        return await self._reprovisioning_repo.stop()

    async def get_current_reprovision(self) -> Reprovisioning | None:
        """Return the current reprovisioning lock."""
        return await self._reprovisioning_repo.get_active_reprovisioning()

    async def init_reprovision(self, requested_by: APIUser, reprovisioning: Reprovisioning) -> None:
        """Initiates reprovisioning by inserting documents into the staging table.

        Deletes all renku entities in the solr core. Then it goes
        through all entities in the postgres datatabase and inserts
        solr documents into the `search_update` table. A background
        process is querying this table and will eventually update
        solr with these entries.
        """

        def log_counter(c: int) -> None:
            if c % 50 == 0:
                logger.info(f"Inserted {c}. entities into staging table...")

        try:
            logger.info(f"Starting reprovisioning with ID {reprovisioning.id}")
            started = datetime.now()
            await self._search_updates_repo.clear_all()
            async with DefaultSolrClient(self._solr_config) as client:
                await client.delete("_type:*")

            counter = 0
            all_users = self._user_repo.get_all_users(requested_by=requested_by)
            counter = await self.__update_entities(all_users, "user", started, counter, log_counter)
            logger.info("Done adding user entities to search_updates table.")

            all_groups = self._group_repo.get_all_groups(requested_by=requested_by)
            counter = await self.__update_entities(all_groups, "group", started, counter, log_counter)
            logger.info("Done adding group entities to search_updates table.")

            all_projects = self._project_repo.get_all_projects(requested_by=requested_by)
            counter = await self.__update_entities(all_projects, "project", started, counter, log_counter)
            logger.info("Done adding project entities to search_updates table.")

            all_dcs = self._data_connector_repo.get_all_data_connectors(requested_by, per_page=20)
            counter = await self.__update_entities(all_dcs, "data connector", started, counter, log_counter)

            logger.info(f"Inserted {counter} entities into the staging table.")

        except Exception as e:
            logger.error("Error while reprovisioning entities!", exc_info=e)
            ## TODO error handling. skip or fail?
        finally:
            await self._reprovisioning_repo.stop()

    async def __update_entities(
        self,
        iter: AsyncGenerator[Project | Group | UserInfo | DataConnector, None],
        name: str,
        started: datetime,
        counter: int,
        on_count: Callable[[int], None],
    ) -> int:
        try:
            async for entity in iter:
                try:
                    await self._search_updates_repo.insert(entity, started)
                    counter += 1
                    on_count(counter)
                except Exception as e:
                    logger.error(f"Error updating search entry for {name} {entity.id}: {e}", exc_info=e)
        except Exception as e:
            logger.error(f"Error updating search entry for {name}s: {e}", exc_info=e)

        return counter
