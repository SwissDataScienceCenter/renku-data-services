"""Utility functions for integrating authzed into search."""

import logging
from collections.abc import Iterable

from authzed.api.v1 import AsyncClient as AuthzClient
from authzed.api.v1 import Consistency, LookupResourcesRequest, ObjectReference, SubjectReference
from authzed.api.v1.permission_service_pb2 import LOOKUP_PERMISSIONSHIP_HAS_PERMISSION

from renku_data_services.authz.models import Role, Scope
from renku_data_services.base_models.core import ResourceType
from renku_data_services.search.user_query import Nel
from renku_data_services.solr.entity_documents import EntityType

logger = logging.getLogger(__name__)


async def __resources_with_permission(
    client: AuthzClient, user_id: str, entity_types: Iterable[EntityType], relation_name: str
) -> list[str]:
    """Get all the resource IDs that a specific user has the given permission/role."""
    user_ref = SubjectReference(object=ObjectReference(object_type=ResourceType.user.value, object_id=user_id))
    result: list[str] = []

    for et in entity_types:
        req = LookupResourcesRequest(
            consistency=Consistency(fully_consistent=True),
            resource_object_type=et.to_resource_type.value,
            permission=relation_name,
            subject=user_ref,
        )
        response = client.LookupResources(req)
        async for o in response:
            if o.permissionship == LOOKUP_PERMISSIONSHIP_HAS_PERMISSION:
                result.append(o.resource_object_id)

    logger.debug(f"Found ids for user '{user_id}' and perm={relation_name}: {result}")
    return result


async def get_non_public_read(client: AuthzClient, user_id: str) -> list[str]:
    """Return all resource ids the given user as access to, that are not public."""
    ets = [e for e in EntityType]
    ets.remove(EntityType.user)  # user don't have this relation
    return await __resources_with_permission(client, user_id, ets, Scope.NON_PUBLIC_READ.value)


async def get_role_ids(client: AuthzClient, user_id: str, roles: Nel[Role]) -> list[str]:
    """Return all resource ids for which the give user has one of the given roles."""
    ets = [e for e in EntityType]
    ets.remove(EntityType.user)  # user don't have this relation
    result: list[str] = []
    for role in roles.to_list():
        r = await __resources_with_permission(client, user_id, ets, role.value)
        result.extend(r)

    return result
