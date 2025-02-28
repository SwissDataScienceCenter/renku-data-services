"""Business logic for searching."""

import logging
from datetime import datetime

from renku_data_services.base_models import APIUser
from renku_data_services.message_queue.db import ReprovisioningRepository
from renku_data_services.message_queue.models import Reprovisioning
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.project.db import ProjectRepository
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.search.models import DeleteDoc
from renku_data_services.solr.solr_client import (
    DefaultSolrClient,
    RawDocument,
    SolrClient,
    SolrClientConfig,
    SolrDocument,
)
from renku_data_services.users.db import UserRepo

logger = logging.getLogger(__name__)


async def reprovision(
    requested_by: APIUser,
    reprovisioning: Reprovisioning,
    search_updates_repo: SearchUpdatesRepo,
    reprovisioning_repo: ReprovisioningRepository,
    solr_config: SolrClientConfig,
    user_repo: UserRepo,
    group_repo: GroupRepository,
    project_repo: ProjectRepository,
) -> None:
    """Initiates reprovisioning by inserting documents into the staging table."""

    def log_counter(c: int) -> None:
        if c % 50 == 0:
            logger.info(f"Inserted {c}. entities into staging table...")

    try:
        logger.info(f"Starting reprovisioning with ID {reprovisioning.id}")
        started = datetime.now()
        await search_updates_repo.clear_all()
        async with DefaultSolrClient(solr_config) as client:
            await client.delete("_type:*")
        counter = 0
        all_users = user_repo.get_all_users(requested_by=requested_by)
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

        logger.info(f"Inserted {counter} entities into the staging table.")

    except Exception as e:
        logger.error("Error while reprovisioning entities!", exc_info=e)
        ## TODO error handling. skip or fail?
    finally:
        await reprovisioning_repo.stop()


async def update_solr(search_updates_repo: SearchUpdatesRepo, solr_client: SolrClient, batch_size: int) -> None:
    """Selects entries from the search staging table and updates SOLR."""
    counter = 0
    while True:
        entries = await search_updates_repo.select_next(batch_size)
        if entries == []:
            break

        ids = [e.id for e in entries]
        try:
            docs: list[SolrDocument] = [RawDocument(e.payload) for e in entries]
            result = await solr_client.upsert(docs)
            if result == "VersionConflict":
                await search_updates_repo.mark_reset(ids)
            else:
                counter = counter + len(entries)
                await search_updates_repo.mark_processed(ids)

            try:
                # In the above upsert, documents could get
                # "soft-deleted". This would finally remove them. As
                # the success of this is not production critical,
                # errors are only logged
                await solr_client.delete(DeleteDoc.solr_query())
            except Exception as de:
                logger.error("Error when removing soft-deleted documents", exc_info=de)

        except Exception as e:
            logger.error(f"Error while updating solr with entities {ids}", exc_info=e)
            try:
                await search_updates_repo.mark_failed(ids)
            except Exception as e2:
                logger.error("Error while setting search entities to failed", exc_info=e2)

    if counter > 0:
        logger.info(f"Updated {counter} entries in SOLR")
