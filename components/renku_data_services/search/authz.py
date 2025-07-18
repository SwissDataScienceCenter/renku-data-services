"""Utility functions for integrating authzed into search."""

import re
from collections.abc import Iterable

from authzed.api.v1 import AsyncClient as AuthzClient
from authzed.api.v1 import Consistency, LookupResourcesRequest, ObjectReference, SubjectReference
from authzed.api.v1.permission_service_pb2 import LOOKUP_PERMISSIONSHIP_HAS_PERMISSION

from renku_data_services.app_config import logging
from renku_data_services.authz.models import Role, Scope
from renku_data_services.base_models.core import ResourceType
from renku_data_services.base_models.nel import Nel
from renku_data_services.solr.entity_documents import EntityType

logger = logging.getLogger(__name__)

__object_id_regex = re.compile("^[a-zA-Z0-9/_|\\-=+]{1,}$")


def __check_authz_object_id(id: str) -> bool:
    """Checks whether the given string is a valid authz object id.

    Unfortunately, I couldn't find anything in the authz python
    package that would do it. You can safely create invalid
    ObjectReferences and send them to authz, only the server will give
    a 400 error back

    The regex is copied from the error response sending the request
    with bad data.

    Since wildcards are not supported for lookup resources, this part
    is removed from the regex and disallowed here.

    """
    return __object_id_regex.fullmatch(id) is not None


async def __resources_with_permission(
    client: AuthzClient, user_id: str, entity_types: Iterable[EntityType], permission_name: str
) -> list[str]:
    """Get all the resource IDs that a specific user has the given permission/role."""
    result: list[str] = []

    if not __check_authz_object_id(user_id):
        logger.debug(f"The user-id passed is not a valid spicedb/authz id: {user_id}")
        return result

    user_ref = SubjectReference(object=ObjectReference(object_type=ResourceType.user.value, object_id=user_id))

    for et in entity_types:
        req = LookupResourcesRequest(
            consistency=Consistency(fully_consistent=True),
            resource_object_type=et.to_resource_type.value,
            permission=permission_name,
            subject=user_ref,
        )
        response = client.LookupResources(req)
        async for o in response:
            if o.permissionship == LOOKUP_PERMISSIONSHIP_HAS_PERMISSION:
                result.append(o.resource_object_id)

    logger.debug(f"Found ids for user:{user_id} perm={permission_name} ets={entity_types}: {result}")
    return result


async def get_non_public_read(client: AuthzClient, user_id: str, ets: Iterable[EntityType]) -> list[str]:
    """Return all resource ids the given user as access to, that are not public."""
    ets = list(ets)
    if EntityType.user in ets:
        ets.remove(EntityType.user)  # user don't have this relation
    return await __resources_with_permission(client, user_id, ets, Scope.NON_PUBLIC_READ.value)


async def get_ids_for_roles(
    client: AuthzClient, user_id: str, roles: Nel[Role], ets: Iterable[EntityType], direct_membership: bool
) -> list[str]:
    """Return all resource ids for which the give user has one of the given roles."""
    ets = list(ets)
    if EntityType.user in ets:
        ets.remove(EntityType.user)  # user don't have this relation
    result: set[str] = set()

    for role in roles:
        match role:
            case Role.VIEWER:
                permission = Scope.DIRECT_MEMBER.value if direct_membership else Scope.EXCLUSIVE_MEMBER.value
            case Role.EDITOR:
                permission = role.value if direct_membership else Scope.EXCLUSIVE_EDITOR.value
            case Role.OWNER:
                permission = role.value if direct_membership else Scope.EXCLUSIVE_OWNER.value

        r = await __resources_with_permission(client, user_id, ets, permission)
        result.update(r)

    return list(result)
