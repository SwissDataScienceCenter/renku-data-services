"""Launch-time selection of the data connectors an app may mount.

Apps are publicly and anonymously reachable and run as ``DUMMY_RENKU_APP_USER_ID``
rather than a real user. The set of data connectors an app mounts is therefore a
**security boundary**: mounting a connector that carries a user's decrypted
credentials would expose that user's data to anonymous visitors. This module
defines the fail-closed filter that decides which of a project's linked connectors
are safe to expose through an app.

A connector is mounted iff **all** of:

1. it is public (owner intent);
2. it needs no static credentials (the UI's "Credentials" box -- ``get_private_fields``);
3. it needs no OAuth integration (the UI's "Integration" box -- ``_OAUTH2_INTEGRATION_STORAGE_TYPES``).

Conditions 2 and 3 are the two halves of "requires nothing from a user"; together
they are what actually guarantee the underlying data is anonymously reachable.
Condition 3 is load-bearing: an OAuth connector set up via connect-account has an
*empty* set of static credential fields, so without it a user's private Google
Drive would pass condition 2 and be mounted into an anonymous public app.

Any error while evaluating the predicate excludes the connector -- fail closed.

See ``docs/adr/0001-mount-data-connectors-into-apps.md``.
"""

from ulid import ULID

from renku_data_services import base_models
from renku_data_services.app_config import logging
from renku_data_services.authz.models import Visibility
from renku_data_services.data_connectors.db import DataConnectorSecretRepository
from renku_data_services.data_connectors.models import (
    DataConnector,
    DataConnectorWithSecrets,
    GlobalDataConnector,
)
from renku_data_services.storage.rclone import RCloneValidator

logger = logging.getLogger(__name__)

_OAUTH2_INTEGRATION_STORAGE_TYPES = frozenset({"drive", "dropbox"})
"""rclone storage types whose credentials come from an OAuth2 integration.

SECURITY: this is the app-side copy of the drive/dropbox -> provider mapping that
``notebooks.data_sources.DataSourceRepository`` uses for sessions. If a new OAuth-backed
storage type is added there, it must be added here too -- otherwise a private connector of
that type would clear this filter and be mounted into an anonymous public app.
"""


def is_app_mountable(dc: DataConnector | GlobalDataConnector, validator: RCloneValidator) -> bool:
    """Return whether a data connector is safe to mount into a public, anonymous app.

    Fail-closed: returns ``False`` on any error evaluating the predicate, so a
    connector is only ever mounted when it has been positively shown to be public
    and to require nothing from a user.
    """
    try:
        return (
            dc.visibility == Visibility.PUBLIC
            and not list(validator.get_private_fields(dc.storage.configuration))
            and dc.storage.configuration.get("type") not in _OAUTH2_INTEGRATION_STORAGE_TYPES
        )
    except Exception:
        logger.warning("Excluding data connector %s from app: predicate error", getattr(dc, "id", "?"), exc_info=True)
        return False


async def select_mountable_connectors(
    user: base_models.APIUser,
    project_id: ULID,
    dc_secret_repo: DataConnectorSecretRepository,
    validator: RCloneValidator,
) -> list[DataConnectorWithSecrets]:
    """Enumerate the project's linked connectors and keep only those safe for an app.

    ``user`` should be the anonymous app identity (``DUMMY_RENKU_APP_USER_ID``): the
    authz layer then only returns publicly-readable connectors, and downstream config
    resolution mints no user tokens -- the same property that makes anonymous sessions
    safe. Enumeration reuses the project-membership model sessions use
    (``DataConnectorToProjectLinkORM``); there is no app-specific connector list.
    """
    survivors: list[DataConnectorWithSecrets] = []
    async for dc in dc_secret_repo.get_data_connectors_with_secrets(user, project_id):
        if is_app_mountable(dc.data_connector, validator):
            survivors.append(dc)

    logger.info(
        "Selected %d data connector(s) to mount for project %s",
        len(survivors),
        project_id,
    )
    return survivors
