"""Functions used to create admins in the authorization database from data in Keycloak."""

from renku_data_services.authz.authz import Authz
from renku_data_services.users.kc_api import IKeycloakAPI


async def sync_admins_from_keycloak(kc_api: IKeycloakAPI, authz: Authz):
    """Query keycloak for all admin users, add or remove any admins from the authorization database as needed."""
    kc_admin_user_ids = [payload["id"] for payload in kc_api.get_admin_users()]
    for admin_id in kc_admin_user_ids:
        change = authz._add_admin(admin_id)
        await authz.client.WriteRelationships(change.apply)
    authz_admins = await authz._get_admin_user_ids()
    for admin_id in authz_admins:
        if admin_id not in kc_admin_user_ids:
            change = await authz._remove_admin(admin_id)
            await authz.client.WriteRelationships(change.apply)
