"""Handling of data sources which require an OAuth2 connection."""

import json
import math
import random
import string
from collections.abc import AsyncIterator
from configparser import ConfigParser
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from sanic import Request
from ulid import ULID

from renku_data_services.app_config import logging
from renku_data_services.authn.renku import RenkuSelfTokenMint
from renku_data_services.base_models import AnonymousAPIUser, AuthenticatedAPIUser
from renku_data_services.base_models.core import APIUser
from renku_data_services.connected_services.db import ConnectedServicesRepository
from renku_data_services.connected_services.models import ProviderKind
from renku_data_services.connected_services.oauth_http import (
    OAuthHttpClientFactory,
)
from renku_data_services.data_connectors.models import (
    DataConnector,
    DataConnectorSecret,
    DataConnectorWithSecrets,
    GlobalDataConnector,
)
from renku_data_services.errors import errors
from renku_data_services.notebooks.api.schemas.cloud_storage import RCloneStorage
from renku_data_services.notebooks.crs import DataSource
from renku_data_services.notebooks.models import ExtraSecret, SessionDataConnectorOverride, SessionExtraResources
from renku_data_services.users.db import UserRepo
from renku_data_services.utils.cryptography import get_encryption_key

if TYPE_CHECKING:
    from renku_data_services.storage.models import RCloneConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True, eq=True, kw_only=True)
class _OAuth2ConfigPartial:
    """Partial configuration; contains OAuth2 fields."""

    token: str
    """Corresponds to the 'token' field in the rclone INI configuration.

    The field is called 'token' but is a JSON object representing an OAuth 2.0 token set.
    Common keys are 'access_token', 'token_type', 'refresh_token' and 'expiry'.
    """

    token_url: str
    """Corresponds to the 'token_url' field in the rclone INI configuration."""


class DataSourceRepository:
    """Repository for handling mounts from data connectors into sessions."""

    def __init__(
        self,
        connected_services_repo: ConnectedServicesRepository,
        oauth_client_factory: OAuthHttpClientFactory,
        user_repo: UserRepo,
        internal_token_mint: RenkuSelfTokenMint,
    ) -> None:
        self.connected_services_repo = connected_services_repo
        self.oauth_client_factory = oauth_client_factory
        self.user_repo = user_repo
        self.internal_token_mint = internal_token_mint

    async def handle_configuration(
        self, request: Request, user: APIUser, data_connector: DataConnector | GlobalDataConnector, scope: str | None
    ) -> dict[str, Any] | None:
        """Ajusts the configuration of the input data connector if it requires an OAuth2 connection.

        Returns either an rclone configuration or None if the data connector should be skipped.
        """
        # NOTE: do not handle global data connectors
        if data_connector.namespace is None:
            return data_connector.storage.configuration

        provider_kind = self._get_oauth2_provider_kind(data_connector=data_connector)
        if provider_kind is None:
            return data_connector.storage.configuration

        oauth2_part = await self._get_oauth2_configuration_part(
            request=request, user=user, data_connector=data_connector, scope=scope
        )
        if oauth2_part is None:
            return None

        logger.info(f"Adjusting rclone configuration for data connector {str(data_connector.id)}.")
        configuration = data_connector.storage.configuration
        if provider_kind == ProviderKind.google:
            configuration["scope"] = configuration.get("scope") or "drive"
        configuration["token"] = oauth2_part.token
        configuration["token_url"] = oauth2_part.token_url
        return configuration

    def is_patching_enabled(self, data_connector: DataConnector | GlobalDataConnector) -> bool:
        """Returns true iff the data connector can be patched."""
        # NOTE: do not handle global data connectors
        if data_connector.namespace is None:
            return False
        provider_kind = self._get_oauth2_provider_kind(data_connector=data_connector)
        return provider_kind is not None

    async def handle_patching_configuration(
        self,
        request: Request,
        user: APIUser,
        data_connector: DataConnector | GlobalDataConnector,
        rclone_ini_config: str,
        scope: str | None,
    ) -> str | None:
        """Handles patching the rclone configuration of a data connector when a session is resumed.

        This method updates the "token" and the "token_url" fields and no other part of the configuration.

        Returns either a new rclone configuration (INI form) or None if the configuration should be left untouched.
        """
        # NOTE: do not handle global data connectors
        if data_connector.namespace is None:
            return None

        parser = ConfigParser(interpolation=None)
        try:
            parser.read_string(rclone_ini_config)
        except Exception as err:
            logger.error(f"Failed to parse existing data connector configuration: {err}")
            return None
        main_section = next(filter(lambda s: s, parser.sections()), "")
        if not main_section:
            logger.error("Failed to parse existing data connector configuration: no main section.")
            return None
        items = parser.items(main_section)
        configuration = dict(items)
        if configuration.get("type") != data_connector.storage.configuration.get("type"):
            logger.warning(
                f"Data connector type changed to {data_connector.storage.configuration.get("type")}, skipping!"
            )
            return None

        oauth2_part = await self._get_oauth2_configuration_part(
            request=request, user=user, data_connector=data_connector, scope=scope
        )
        if oauth2_part is None:
            return None

        logger.info(f"Patching rclone configuration for data connector {str(data_connector.id)}.")
        parser.set(main_section, "token", oauth2_part.token)
        parser.set(main_section, "token_url", oauth2_part.token_url)
        stringio = StringIO()
        parser.write(stringio)
        return stringio.getvalue()

    async def handle_configuration_for_test(
        self, user: APIUser, configuration: "RCloneConfig | dict[str, Any]"
    ) -> "RCloneConfig | dict[str, Any] | None":
        """Ajusts the input configuration if it requires an OAuth2 connection.

        Returns either an rclone configuration or None if the data connector should be skipped.
        """
        provider_kind: ProviderKind | None = None
        match configuration.get("type"):
            case "drive":
                provider_kind = ProviderKind.google
            case "dropbox":
                provider_kind = ProviderKind.dropbox
        if provider_kind is None:
            return configuration

        provider = await self.connected_services_repo.get_provider_for_kind(user=user, provider_kind=provider_kind)
        if provider is None:
            return None
        connection = provider.connected_user.connection if provider.connected_user else None
        if connection is None:
            return None
        token_set = await self.connected_services_repo.get_token_set(user=user, connection_id=connection.id)
        if not token_set or not token_set.access_token:
            return None
        token_config = {
            "access_token": token_set.access_token,
            "token_type": "Bearer",
        }
        if provider_kind == ProviderKind.google:
            configuration["scope"] = configuration.get("scope") or "drive"
        if token_set.expires_at_iso:
            token_config["expiry"] = token_set.expires_at_iso
        configuration["token"] = json.dumps(token_config)
        return configuration

    def _get_oauth2_provider_kind(self, data_connector: DataConnector | GlobalDataConnector) -> ProviderKind | None:
        """Returns the provider kind for data connectors which require an OAuth2 configuration."""
        match data_connector.storage.configuration["type"]:
            case "drive":
                return ProviderKind.google
            case "dropbox":
                return ProviderKind.dropbox
            case _:
                return None

    async def _get_oauth2_configuration_part(
        self,
        request: Request,
        user: APIUser,
        data_connector: DataConnector,
        scope: str | None,
    ) -> _OAuth2ConfigPartial | None:
        """Get the OAuth2 configuration fields."""
        provider_kind = self._get_oauth2_provider_kind(data_connector=data_connector)
        if provider_kind is None:
            return None

        provider = await self.connected_services_repo.get_provider_for_kind(user=user, provider_kind=provider_kind)
        if provider is None:
            logger.info(
                f"Skipping data connector {str(data_connector.id)} of type "
                f"{data_connector.storage.configuration["type"]} "
                f"because no provider of kind {provider_kind.value} was found."
            )
            return None
        connection = provider.connected_user.connection if provider.connected_user else None
        if connection is None:
            logger.info(
                f"Skipping data connector {str(data_connector.id)} of type "
                f"{data_connector.storage.configuration["type"]} "
                f"because no active connection was found; user needs to connect with {provider.provider.id}."
            )
            return None
        token_set = await self.connected_services_repo.get_token_set(user=user, connection_id=connection.id)
        if not token_set or not token_set.access_token:
            logger.info(
                f"Skipping data connector {str(data_connector.id)} of type "
                f"{data_connector.storage.configuration["type"]} "
                f"because the connection is not active; user needs to re-connect with {provider.provider.id}."
            )
            return None
        token_config = {
            "access_token": token_set.access_token,
            "token_type": "Bearer",
        }
        # if user.access_token and user.refresh_token:
        #     renku_tokens = RenkuTokens(
        #         access_token=user.access_token,
        #         refresh_token=user.refresh_token,
        #     )
        #     token_config["refresh_token"] = renku_tokens.encode()
        # TODO: scope
        expires_in_td = self.internal_token_mint.refresh_token_expiration
        expires_in = math.floor(expires_in_td.total_seconds())
        renku_token = self.internal_token_mint.create_token(user=user, scope=scope, expires_in=expires_in_td)
        token_config["refresh_token"] = renku_token

        if token_set.expires_at:
            exp = datetime.fromtimestamp(token_set.expires_at, UTC)
            expires_in_token_set = math.floor((exp - datetime.now(UTC)).total_seconds())
            expires_in = min(expires_in, expires_in_token_set)

        token_config["expiry"] = (datetime.now(UTC) + timedelta(seconds=expires_in)).isoformat()

        token = json.dumps(token_config)
        token_url = request.url_for("oauth2_connections.post_token_endpoint", connection_id=connection.id)
        return _OAuth2ConfigPartial(token=token, token_url=token_url)

    async def get_data_sources(
        self,
        request: Request,
        user: AnonymousAPIUser | AuthenticatedAPIUser,
        base_name: str,
        data_connectors_stream: AsyncIterator[DataConnectorWithSecrets],
        work_dir: PurePosixPath,
        data_connectors_overrides: list[SessionDataConnectorOverride],
        namespace: str,
        storage_class: str,
    ) -> SessionExtraResources:
        """Generate cloud storage related resources."""
        data_sources: list[DataSource] = []
        secrets: list[ExtraSecret] = []
        dcs: dict[str, RCloneStorage] = {}
        dcs_secrets: dict[str, list[DataConnectorSecret]] = {}
        user_secret_key: str | None = None
        internal_token_scope = f"session:{base_name}"  # TODO: handle session vs job
        async for dc in data_connectors_stream:
            configuration = await self.handle_configuration(
                request=request,
                user=user,
                data_connector=dc.data_connector,
                scope=internal_token_scope,
            )
            if configuration is None:
                continue
            mount_folder = (
                dc.data_connector.storage.target_path
                if PurePosixPath(dc.data_connector.storage.target_path).is_absolute()
                else (work_dir / dc.data_connector.storage.target_path).as_posix()
            )
            dcs[str(dc.data_connector.id)] = RCloneStorage(
                source_path=dc.data_connector.storage.source_path,
                mount_folder=mount_folder,
                configuration=configuration,
                readonly=dc.data_connector.storage.readonly,
                name=dc.data_connector.name,
                secrets={str(secret.secret_id): secret.name for secret in dc.secrets},
                storage_class=storage_class,
            )
            if len(dc.secrets) > 0:
                dcs_secrets[str(dc.data_connector.id)] = dc.secrets
        if isinstance(user, AuthenticatedAPIUser) and len(dcs_secrets) > 0:
            secret_key = await self.user_repo.get_or_create_user_secret_key(user)
            user_secret_key = get_encryption_key(secret_key.encode(), user.id.encode()).decode("utf-8")
        # NOTE: Check the cloud storage overrides from the request body and if any match
        # then overwrite the projects cloud storages
        # NOTE: Cloud storages in the session launch request body that are not from the DB will cause a 404 error
        # TODO: Is the below statement correct?
        # NOTE: Overriding the configuration when a saved secret is there will cause a 422 error
        for dco in data_connectors_overrides:
            dc_id = str(dco.data_connector_id)
            if dc_id not in dcs:
                raise errors.MissingResourceError(
                    message=f"You have requested a data connector with ID {dc_id} which does not exist "
                    "or you don't have access to."
                )
            # NOTE: if 'skip' is true, we do not mount that data connector
            if dco.skip:
                del dcs[dc_id]
                continue
            if dco.target_path is not None and not PurePosixPath(dco.target_path).is_absolute():
                dco.target_path = (work_dir / dco.target_path).as_posix()
            dcs[dc_id] = dcs[dc_id].with_override(dco)

        # Handle potential duplicate target_path
        dcs = _deduplicate_target_paths(dcs)

        for cs_id, cs in dcs.items():
            secret_name = f"{base_name}-ds-{cs_id.lower()}"
            secret_key_needed = len(dcs_secrets.get(cs_id, [])) > 0
            if secret_key_needed and user_secret_key is None:
                raise errors.ProgrammingError(
                    message=f"You have saved storage secrets for data connector {cs_id} "
                    f"associated with your user ID {user.id} but no key to decrypt them, "
                    "therefore we cannot mount the requested data connector. "
                    "Please report this to the renku administrators."
                )
            secret = ExtraSecret(
                cs.secret(
                    secret_name,
                    namespace,
                    user_secret_key=user_secret_key if secret_key_needed else None,
                )
            )
            secrets.append(secret)
            data_sources.append(
                DataSource(
                    mountPath=cs.mount_folder,
                    secretRef=secret.ref(),
                    accessMode="ReadOnlyMany" if cs.readonly else "ReadWriteOnce",
                )
            )
        return SessionExtraResources(
            data_sources=data_sources,
            secrets=secrets,
            data_connector_secrets=dcs_secrets,
        )


def _deduplicate_target_paths(dcs: dict[str, RCloneStorage]) -> dict[str, RCloneStorage]:
    """Ensures that the target paths for all storages are unique.

    This method will attempt to de-duplicate the target_path for all items passed in,
    and raise an error if it fails to generate unique target_path.
    """
    result_dcs: dict[str, RCloneStorage] = {}
    mount_folders: dict[str, list[str]] = {}

    def _find_mount_folder(dc: RCloneStorage) -> str:
        mount_folder = dc.mount_folder
        if mount_folder not in mount_folders:
            return mount_folder
        # 1. Try with a "-1", "-2", etc. suffix
        mount_folder_try = f"{mount_folder}-{len(mount_folders[mount_folder])}"
        if mount_folder_try not in mount_folders:
            return mount_folder_try
        # 2. Try with a random suffix
        suffix = "".join([random.choice(string.ascii_lowercase + string.digits) for _ in range(4)])  # nosec B311
        mount_folder_try = f"{mount_folder}-{suffix}"
        if mount_folder_try not in mount_folders:
            return mount_folder_try
        raise errors.ValidationError(
            message=f"Could not start session because two or more data connectors ({', '.join(mount_folders[mount_folder])}) share the same mount point '{mount_folder}'"  # noqa E501
        )

    for dc_id, dc in dcs.items():
        original_mount_folder = dc.mount_folder
        new_mount_folder = _find_mount_folder(dc)
        # Keep track of the original mount folder here
        if new_mount_folder != original_mount_folder:
            logger.warning(f"Re-assigning data connector {dc_id} to mount point '{new_mount_folder}'")
            dc_ids = mount_folders.get(original_mount_folder, [])
            dc_ids.append(dc_id)
            mount_folders[original_mount_folder] = dc_ids
        # Keep track of the assigned mount folder here
        dc_ids = mount_folders.get(new_mount_folder, [])
        dc_ids.append(dc_id)
        mount_folders[new_mount_folder] = dc_ids
        result_dcs[dc_id] = dc.with_override(
            override=SessionDataConnectorOverride(
                skip=False,
                data_connector_id=ULID.from_str(dc_id),
                target_path=new_mount_folder,
                configuration=None,
                source_path=None,
                readonly=None,
            )
        )

    return result_dcs
