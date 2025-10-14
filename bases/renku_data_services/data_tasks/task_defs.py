"""The task definitions in form of coroutines."""

import asyncio

from authzed.api.v1 import (
    Consistency,
    LookupResourcesRequest,
    ObjectReference,
    ReadRelationshipsRequest,
    Relationship,
    RelationshipFilter,
    RelationshipUpdate,
    SubjectFilter,
    SubjectReference,
    WriteRelationshipsRequest,
)
from ulid import ULID

import renku_data_services.authz.admin_sync as admin_sync
import renku_data_services.search.core as search_core
from renku_data_services import errors
from renku_data_services.app_config import logging
from renku_data_services.authz.authz import ResourceType, _AuthzConverter, _Relation
from renku_data_services.authz.models import Scope
from renku_data_services.base_models.core import InternalServiceAdmin, ServiceAdminId
from renku_data_services.base_models.metrics import MetricsEvent
from renku_data_services.data_tasks.dependencies import DependencyManager
from renku_data_services.data_tasks.taskman import TaskDefininions
from renku_data_services.namespace.models import NamespaceKind
from renku_data_services.solr.solr_client import DefaultSolrClient

logger = logging.getLogger(__name__)


async def update_search(dm: DependencyManager) -> None:
    """Update the SOLR with data from the search staging table."""
    while True:
        async with DefaultSolrClient(dm.config.solr) as client:
            await search_core.update_solr(dm.search_updates_repo, client, 20)
        await asyncio.sleep(1)


async def send_metrics_to_posthog(dm: DependencyManager) -> None:
    """Send pending product metrics to posthog."""
    from posthog import Posthog

    posthog = Posthog(
        api_key=dm.config.posthog.api_key,
        host=dm.config.posthog.host,
        sync_mode=True,
        super_properties={"environment": dm.config.posthog.environment},
    )

    while True:
        try:
            metrics = dm.metrics_repo.get_unprocessed_metrics()

            processed_ids = []
            async for metric in metrics:
                try:
                    if metric.event == MetricsEvent.identify_user.value:
                        posthog.identify(
                            distinct_id=metric.anonymous_user_id,
                            timestamp=metric.timestamp,
                            properties=metric.metadata or {},
                            uuid=metric.id.to_uuid4(),
                        )
                    else:
                        posthog.capture(
                            distinct_id=metric.anonymous_user_id,
                            timestamp=metric.timestamp,
                            event=metric.event,
                            properties=metric.metadata_ or {},
                            # This is sent to avoid duplicate events if multiple instances of data service are running.
                            # Posthog deduplicates events with the same timestamp, distinct_id, event, and uuid fields:
                            # https://github.com/PostHog/posthog/issues/17211#issuecomment-1723136534
                            uuid=metric.id.to_uuid4(),
                        )
                except Exception as e:
                    logger.error(f"Failed to process metrics event {metric.id}: {e}")
                else:
                    processed_ids.append(metric.id)

            await dm.metrics_repo.delete_processed_metrics(processed_ids)
        except (asyncio.CancelledError, KeyboardInterrupt) as e:
            logger.warning(f"Exiting: {e}")
            return
        else:
            # NOTE: Sleep 10 seconds between processing cycles
            await asyncio.sleep(10)


async def generate_user_namespaces(dm: DependencyManager) -> None:
    """Generate namespaces for users if there are none."""
    while True:
        try:
            await dm.group_repo.generate_user_namespaces()
        except (asyncio.CancelledError, KeyboardInterrupt) as e:
            logger.warning(f"Exiting: {e}")
        else:
            await asyncio.sleep(dm.config.short_task_period_s)


async def sync_user_namespaces(dm: DependencyManager) -> None:
    """Lists all user namespaces in the database and adds them to Authzed and the event queue."""
    user_namespaces = dm.group_repo._get_user_namespaces()
    logger.info("Start syncing user namespaces to the authorization DB and message queue")
    num_authz: int = 0
    num_events: int = 0
    num_total: int = 0
    async for user_namespace in user_namespaces:
        num_total += 1
        authz_change = dm.authz._add_user_namespace(user_namespace.namespace)
        session = dm.config.db.async_session_maker()
        tx = session.begin()
        await tx.start()
        try:
            await dm.authz.client.WriteRelationships(authz_change.apply)
            num_authz += 1
        except Exception as err:
            # NOTE: We do not rollback the authz changes here because it is OK if something is in Authz DB
            # but not in the message queue but not vice-versa.
            logger.error(f"Failed to sync user namespace {user_namespace} because {err}")
            await tx.rollback()
        else:
            await tx.commit()
        finally:
            await session.close()
    logger.info(f"Wrote authorization changes for {num_authz}/{num_total} user namespaces")
    logger.info(f"Wrote to event queue database for {num_events}/{num_total} user namespaces")


async def bootstrap_user_namespaces(dm: DependencyManager) -> None:
    """Synchronize user namespaces to the authorization database only if none are already present."""
    while True:
        try:
            rels = aiter(
                dm.authz.client.ReadRelationships(
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
                logger.info(
                    "Found at least 5 user namespace in the authorization database, "
                    "will not sync user namespaces to authorization."
                )
                return
            await sync_user_namespaces(dm)
        except (asyncio.CancelledError, KeyboardInterrupt) as e:
            logger.warning(f"Exiting: {e}")
        else:
            if dm.config.dummy_stores:
                # only run once in tests
                return
            await asyncio.sleep(dm.config.short_task_period_s)


async def fix_mismatched_project_namespace_ids(dm: DependencyManager) -> None:
    """Fixes a problem where the project namespace relationship for projects has the wrong group ID."""
    while True:
        try:
            api_user = InternalServiceAdmin(id=ServiceAdminId.migrations)
            res = dm.authz.client.ReadRelationships(
                ReadRelationshipsRequest(
                    consistency=Consistency(fully_consistent=True),
                    relationship_filter=RelationshipFilter(
                        resource_type=ResourceType.project,
                        optional_relation=_Relation.project_namespace.value,
                        optional_subject_filter=SubjectFilter(subject_type=ResourceType.group.value),
                    ),
                )
            )
            async for rel in res:
                logger.info(f"Checking project namespace - group relation {rel} for correct group ID")
                project_id = rel.relationship.resource.object_id
                try:
                    project = await dm.project_repo.get_project(api_user, project_id)
                except errors.MissingResourceError:
                    logger.info(f"Couldn't find project {project_id}, deleting relation")
                    await dm.authz.client.WriteRelationships(
                        WriteRelationshipsRequest(
                            updates=[
                                RelationshipUpdate(
                                    operation=RelationshipUpdate.OPERATION_DELETE,
                                    relationship=rel.relationship,
                                ),
                            ]
                        )
                    )
                    continue

                if project.namespace.kind != NamespaceKind.group:
                    continue
                correct_group_id = project.namespace.underlying_resource_id
                authzed_group_id = rel.relationship.subject.object.object_id
                if authzed_group_id != correct_group_id:
                    logger.info(
                        f"The project namespace ID in Authzed {authzed_group_id} "
                        f"does not match the expected group ID {correct_group_id}, correcting it..."
                    )
                    await dm.authz.client.WriteRelationships(
                        WriteRelationshipsRequest(
                            updates=[
                                RelationshipUpdate(
                                    operation=RelationshipUpdate.OPERATION_TOUCH,
                                    relationship=Relationship(
                                        resource=rel.relationship.resource,
                                        relation=rel.relationship.relation,
                                        subject=SubjectReference(
                                            object=ObjectReference(
                                                object_type=ResourceType.group.value, object_id=str(correct_group_id)
                                            )
                                        ),
                                    ),
                                ),
                                RelationshipUpdate(
                                    operation=RelationshipUpdate.OPERATION_DELETE,
                                    relationship=rel.relationship,
                                ),
                            ]
                        )
                    )
        except (asyncio.CancelledError, KeyboardInterrupt) as e:
            logger.warning(f"Exiting: {e}")
        else:
            if dm.config.dummy_stores:
                # only run once in tests
                return
            await asyncio.sleep(dm.config.short_task_period_s)


async def migrate_groups_make_all_public(dm: DependencyManager) -> None:
    """Update existing groups to make them public."""
    while True:
        try:
            all_groups = dm.authz.client.ReadRelationships(
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
            logger.info(f"All groups = {all_group_ids}")

            public_groups = dm.authz.client.LookupResources(
                LookupResourcesRequest(
                    resource_object_type=ResourceType.group.value,
                    permission=Scope.READ.value,
                    subject=SubjectReference(object=_AuthzConverter.anonymous_user()),
                )
            )
            public_group_ids: set[str] = set()
            async for group in public_groups:
                public_group_ids.add(group.resource_object_id)
            logger.info(f"Public groups = {len(public_group_ids)}")
            logger.info(f"Public groups = {public_group_ids}")

            groups_to_process = all_group_ids - public_group_ids
            logger.info(f"Groups to process = {groups_to_process}")

            all_users = SubjectReference(object=_AuthzConverter.all_users())
            all_anon_users = SubjectReference(object=_AuthzConverter.anonymous_users())
            for group_id in groups_to_process:
                group_res = _AuthzConverter.group(ULID.from_str(group_id))
                all_users_are_viewers = Relationship(
                    resource=group_res,
                    relation=_Relation.public_viewer.value,
                    subject=all_users,
                )
                all_anon_users_are_viewers = Relationship(
                    resource=group_res,
                    relation=_Relation.public_viewer.value,
                    subject=all_anon_users,
                )
                authz_change = WriteRelationshipsRequest(
                    updates=[
                        RelationshipUpdate(operation=RelationshipUpdate.OPERATION_TOUCH, relationship=rel)
                        for rel in [all_users_are_viewers, all_anon_users_are_viewers]
                    ]
                )
                await dm.authz.client.WriteRelationships(authz_change)
                logger.info(f"Made group {group_id} public")
        except (asyncio.CancelledError, KeyboardInterrupt) as e:
            logger.warning(f"Exiting: {e}")
        else:
            if dm.config.dummy_stores:
                # only run once in tests
                return
            await asyncio.sleep(dm.config.short_task_period_s)


async def migrate_user_namespaces_make_all_public(dm: DependencyManager) -> None:
    """Update existing user namespaces to make them public."""
    while True:
        try:
            all_user_namespaces = dm.authz.client.ReadRelationships(
                ReadRelationshipsRequest(
                    relationship_filter=RelationshipFilter(
                        resource_type=ResourceType.user_namespace.value,
                        optional_relation=_Relation.user_namespace_platform.value,
                    )
                )
            )
            all_user_namespace_ids: set[str] = set()
            async for ns in all_user_namespaces:
                all_user_namespace_ids.add(ns.relationship.resource.object_id)
            logger.info(f"All user namespaces = {len(all_user_namespace_ids)}")
            logger.info(f"All user namespaces = {all_user_namespace_ids}")

            public_user_namespaces = dm.authz.client.LookupResources(
                LookupResourcesRequest(
                    resource_object_type=ResourceType.user_namespace.value,
                    permission=Scope.READ.value,
                    subject=SubjectReference(object=_AuthzConverter.anonymous_user()),
                )
            )
            public_user_namespace_ids: set[str] = set()
            async for ns in public_user_namespaces:
                public_user_namespace_ids.add(ns.resource_object_id)
            logger.info(f"Public user namespaces = {len(public_user_namespace_ids)}")
            logger.info(f"Public user namespaces = {public_user_namespace_ids}")

            namespaces_to_process = all_user_namespace_ids - public_user_namespace_ids
            logger.info(f"User namespaces to process = {namespaces_to_process}")

            all_users = SubjectReference(object=_AuthzConverter.all_users())
            all_anon_users = SubjectReference(object=_AuthzConverter.anonymous_users())
            for ns_id in namespaces_to_process:
                namespace_res = _AuthzConverter.user_namespace(ULID.from_str(ns_id))
                all_users_are_viewers = Relationship(
                    resource=namespace_res,
                    relation=_Relation.public_viewer.value,
                    subject=all_users,
                )
                all_anon_users_are_viewers = Relationship(
                    resource=namespace_res,
                    relation=_Relation.public_viewer.value,
                    subject=all_anon_users,
                )
                authz_change = WriteRelationshipsRequest(
                    updates=[
                        RelationshipUpdate(operation=RelationshipUpdate.OPERATION_TOUCH, relationship=rel)
                        for rel in [all_users_are_viewers, all_anon_users_are_viewers]
                    ]
                )
                await dm.authz.client.WriteRelationships(authz_change)
                logger.info(f"Made user namespace {ns_id} public")
        except (asyncio.CancelledError, KeyboardInterrupt) as e:
            logger.warning(f"Exiting: {e}")
        else:
            if dm.config.dummy_stores:
                # only run once in tests
                return
            await asyncio.sleep(dm.config.short_task_period_s)


async def users_sync(dm: DependencyManager) -> None:
    """Sync all users from keycloak."""
    while True:
        try:
            await dm.syncer.users_sync(dm.kc_api)

        except (asyncio.CancelledError, KeyboardInterrupt) as e:
            logger.warning(f"Exiting: {e}")
        else:
            await asyncio.sleep(dm.config.long_task_period_s)


async def sync_admins_from_keycloak(dm: DependencyManager) -> None:
    """Sync all users from keycloak."""
    while True:
        try:
            await admin_sync.sync_admins_from_keycloak(dm.kc_api, dm.authz)

        except (asyncio.CancelledError, KeyboardInterrupt) as e:
            logger.warning(f"Exiting: {e}")
        else:
            await asyncio.sleep(dm.config.long_task_period_s)


def all_tasks(dm: DependencyManager) -> TaskDefininions:
    """A dict of task factories to be managed in main."""
    # Impl. note: We pass the entire config to the coroutines, because
    # should such a task fail it will be restarted, which means the
    # coroutine is re-created. In this case it might be better to also
    # re-create its entire state. If we pass already created
    # repositories or other services (and they are not stateless) we
    # might capture this state and possibly won't recover by
    # re-entering the coroutine.
    return TaskDefininions(
        {
            "update_search": lambda: update_search(dm),
            "send_product_metrics": lambda: send_metrics_to_posthog(dm),
            "generate_user_namespace": lambda: generate_user_namespaces(dm),
            "bootstrap_user_namespaces": lambda: bootstrap_user_namespaces(dm),
            "fix_mismatched_project_namespace_ids": lambda: fix_mismatched_project_namespace_ids(dm),
            "migrate_groups_make_all_public": lambda: migrate_groups_make_all_public(dm),
            "migrate_user_namespaces_make_all_public": lambda: migrate_user_namespaces_make_all_public(dm),
            "users_sync": lambda: users_sync(dm),
            "sync_admins_from_keycloak": lambda: sync_admins_from_keycloak(dm),
        }
    )
