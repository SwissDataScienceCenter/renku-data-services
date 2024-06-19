"""Different utility functions for background jobs."""

import logging

from authzed.api.v1.core_pb2 import SubjectReference
from authzed.api.v1.permission_service_pb2 import (
    LookupResourcesRequest,
    ReadRelationshipsRequest,
    RelationshipFilter,
)

from renku_data_services.authz.authz import Authz, ResourceType, _AuthzConverter, _Relation
from renku_data_services.authz.models import Scope
from renku_data_services.background_jobs.config import SyncConfig
from renku_data_services.message_queue.avro_models.io.renku.events import v2
from renku_data_services.message_queue.converters import EventConverter


async def sync_user_namespaces(config: SyncConfig) -> None:
    """Lists all user namespaces in the database and adds them to Authzed and the event queue."""
    authz = Authz(config.authz_config)
    user_namespaces = config.group_repo._get_user_namespaces()
    logging.info("Start syncing user namespaces to the authorization DB and message queue")
    num_authz: int = 0
    num_events: int = 0
    num_total: int = 0
    async for user_namespace in user_namespaces:
        num_total += 1
        events = EventConverter.to_events(user_namespace, v2.UserAdded)
        authz_change = authz._add_user_namespace(user_namespace.namespace)
        session = config.session_maker()
        tx = session.begin()
        await tx.start()
        try:
            await authz.client.WriteRelationships(authz_change.apply)
            num_authz += 1
            for event in events:
                await config.event_repo.store_event(session, event)
            num_events += 1
        except Exception as err:
            # NOTE: We do not rollback the authz changes here because it is OK if something is in Authz DB
            # but not in the message queue but not vice-versa.
            logging.error(f"Failed to sync user namespace {user_namespace} because {err}")
            await tx.rollback()
        else:
            await tx.commit()
        finally:
            await session.close()
    logging.info(f"Wrote authorization changes for {num_authz}/{num_total} user namespaces")
    logging.info(f"Wrote to event queue database for {num_events}/{num_total} user namespaces")


async def bootstrap_user_namespaces(config: SyncConfig) -> None:
    """Synchronize user namespaces to the authorization database only if none are already present."""
    authz = Authz(config.authz_config)
    rels = aiter(
        authz.client.ReadRelationships(
            ReadRelationshipsRequest(
                relationship_filter=RelationshipFilter(
                    resource_type=ResourceType.user_namespace.value, optional_relation=_Relation.owner.value
                )
            )
        )
    )
    num_rels = 0
    for _ in range(5):
        if await anext(rels, None) is not None:
            num_rels += 1
    if num_rels >= 5:
        logging.info(
            "Found at least 5 user namespace in the authorization database, "
            "will not sync user namespaces to authorization."
        )
        return
    await sync_user_namespaces(config)


async def migrate_groups(config: SyncConfig) -> None:
    """Update existing groups to make them public."""
    logger = logging.getLogger("migrate_groups")
    logger.setLevel(logging.INFO)

    authz = Authz(config.authz_config)
    all_groups = authz.client.ReadRelationships(
        ReadRelationshipsRequest(
            relationship_filter=RelationshipFilter(
                resource_type=ResourceType.group.value,
                optional_relation=_Relation.group_platform.value,
            )
        )
    )
    all_group_ids: set[str] = set()
    async for group in all_groups:
        all_group_ids.add(group.relationship.resource.object_id)
    logger.info(f"All groups = {len(all_group_ids)}")
    print(f"All groups = {len(all_group_ids)}")
    print(f"All groups = {all_group_ids}")
    public_groups = authz.client.LookupResources(
        LookupResourcesRequest(
            resource_object_type=ResourceType.group.value,
            permission=Scope.READ.value,
            subject=SubjectReference(object=_AuthzConverter.anonymous_user()),
        )
    )
    public_group_ids: set[str] = set()
    async for group in public_groups:
        public_group_ids.add(group.resource_object_id)
    print(f"Public groups = {len(public_group_ids)}")
    print(f"Public groups = {public_group_ids}")
    groups_to_process = all_group_ids - public_group_ids
    print(f"Groups to process = {groups_to_process}")
