"""Code for reprovisioning the search index."""

from collections.abc import AsyncGenerator, Callable
from datetime import datetime

from renku_data_services.app_config import logging
from renku_data_services.base_api.pagination import PaginationRequest
from renku_data_services.base_models.core import APIUser
from renku_data_services.data_connectors.db import DataConnectorRepository
from renku_data_services.data_connectors.models import DataConnector, GlobalDataConnector
from renku_data_services.errors.errors import ForbiddenError
from renku_data_services.message_queue.db import ReprovisioningRepository
from renku_data_services.message_queue.models import Reprovisioning
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.namespace.models import Group
from renku_data_services.project.db import ProjectRepository
from renku_data_services.project.models import Project
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.solr import entity_schema
from renku_data_services.solr.solr_client import DefaultSolrAdminClient, DefaultSolrClient, SolrClientConfig
from renku_data_services.solr.solr_migrate import SchemaMigrator
from renku_data_services.users.db import UserRepo
from renku_data_services.users.models import UserInfo

logger = logging.getLogger(__name__)


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

    async def run_reprovision(self, admin: APIUser, migrate_solr_schema: bool = True) -> int:
        """Start a reprovisioning if not already running."""
        reprovision = await self.acquire_reprovision()
        return await self.init_reprovision(admin, reprovision, migrate_solr_schema)

    async def acquire_reprovision(self) -> Reprovisioning:
        """Acquire a reprovisioning slot. Throws if already taken."""
        return await self._reprovisioning_repo.start()

    async def kill_reprovision_lock(self) -> None:
        """Removes an existing reprovisioning lock."""
        return await self._reprovisioning_repo.stop()

    async def get_current_reprovision(self) -> Reprovisioning | None:
        """Return the current reprovisioning lock."""
        return await self._reprovisioning_repo.get_active_reprovisioning()

    async def _get_all_data_connectors(
        self, user: APIUser, per_page: int = 20
    ) -> AsyncGenerator[DataConnector | GlobalDataConnector, None]:
        """Get all data connectors, retrieving `per_page` each time."""
        preq = PaginationRequest(page=1, per_page=per_page)
        result: tuple[list[DataConnector | GlobalDataConnector], int] | None = None
        count: int = 0
        while result is None or result[1] > count:
            result = await self._data_connector_repo.get_data_connectors(user=user, pagination=preq)
            count = count + len(result[0])
            preq = PaginationRequest(page=preq.page + 1, per_page=per_page)
            for dc in result[0]:
                yield dc

    async def init_reprovision(
        self, admin: APIUser, reprovisioning: Reprovisioning, migrate_solr_schema: bool = True
    ) -> int:
        """Initiates reprovisioning by inserting documents into the staging table.

        Deletes all renku entities in the solr core. Then it goes
        through all entities in the postgres datatabase and inserts
        solr documents into the `search_update` table. A background
        process is querying this table and will eventually update
        solr with these entries.
        """

        if not admin.is_admin:
            raise ForbiddenError(message="Only Renku administrators are allowed to start search reprovisioning.")

        def log_counter(c: int) -> None:
            if c % 50 == 0:
                logger.info(f"Inserted {c}. entities into staging table...")

        migrator = SchemaMigrator(self._solr_config)
        counter = 0
        try:
            logger.info(f"Starting reprovisioning with ID {reprovisioning.id}")
            started = datetime.now()
            await self._search_updates_repo.clear_all()
            async with DefaultSolrClient(self._solr_config) as client:
                res = await client.delete("_type:*")
                if res.status_code != 200:
                    logger.error(
                        f"Failed to delete all documents in solr during reprovisioning: {res.text}, "
                        f"status_code: {res.status_code}",
                        exc_info=False,
                    )
                async with DefaultSolrAdminClient(self._solr_config) as admin_client:
                    res = await admin_client.reload(None)
                    if res.status_code != 200:
                        logger.error(
                            f"Failed to reload solr core during reprovisioning: {res.text}, "
                            f"status code: {res.status_code}",
                            exc_info=False,
                        )

            if migrate_solr_schema:
                await migrator.migrate(entity_schema.all_migrations)

            all_users = self._user_repo.get_all_users(requested_by=admin)
            counter = await self.__update_entities(all_users, "user", started, counter, log_counter)
            logger.info(f"Done adding user entities to search_updates table. Record count: {counter}.")

            all_groups = self._group_repo.get_all_groups(requested_by=admin)
            counter = await self.__update_entities(all_groups, "group", started, counter, log_counter)
            logger.info(f"Done adding group entities to search_updates table. Record count: {counter}")

            all_projects = self._project_repo.get_all_projects(requested_by=admin)
            counter = await self.__update_entities(all_projects, "project", started, counter, log_counter)
            logger.info(f"Done adding project entities to search_updates table. Record count: {counter}")

            all_dcs = self._get_all_data_connectors(admin, per_page=20)
            counter = await self.__update_entities(all_dcs, "data connector", started, counter, log_counter)
            logger.info(f"Done adding dataconnector entities to search_updates table. Record count: {counter}")

            logger.info(f"Inserted {counter} entities into the staging table.")
        except Exception as e:
            logger.error("Error while reprovisioning entities!", exc_info=e)
            ## TODO error handling. skip or fail?
        finally:
            await self._reprovisioning_repo.stop()

        return counter

    async def __update_entities(
        self,
        iter: AsyncGenerator[Project | Group | UserInfo | DataConnector | GlobalDataConnector, None],
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
