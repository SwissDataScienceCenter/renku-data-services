"""Different utility functions for background jobs."""

import logging

from authzed.api.v1.permission_service_pb2 import ReadRelationshipsRequest, RelationshipFilter

from renku_data_services.authz.authz import Authz, ResourceType, _Relation
from renku_data_services.background_jobs.config import SyncConfig
from renku_data_services.message_queue.avro_models.io.renku.events import v2
from renku_data_services.message_queue.converters import EventConverter


async def sync_user_namespaces(config: SyncConfig):
    """Lists all user namespaces in the database and adds them to Authzed and the event queue."""
    authz = Authz(config.authz_config)
    user_namespaces = await config.group_repo._get_user_namespaces()
    logging.info(f"Start syncing {len(user_namespaces)} to the authorization DB and message queue")
    for user_namespace in user_namespaces:
        events = EventConverter.to_events(user_namespace, v2.UserAdded)
        authz_change = authz._add_user_namespace(user_namespace.namespace)
        session = config.session_maker()
        tx = session.begin()
        await tx.start()
        try:
            await authz.client.WriteRelationships(authz_change.apply)
            for event in events:
                await config.event_repo.store_event(session, event)
        except Exception as err:
            logging.error(f"Failed to sync user namespace {user_namespace} because {err}")
            await tx.rollback()
        else:
            await tx.commit()
        finally:
            await session.close()
    logging.info(f"Wrote authorization changes and events for {len(user_namespaces)} user namespaces")


async def bootstrap_user_namespaces(config: SyncConfig):
    """Sycnhornize user namespaces to the authorization database only if none are already present."""
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
