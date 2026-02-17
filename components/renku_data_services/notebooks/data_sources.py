"""Handling of data sources which require an OAuth2 connection."""

import json
from configparser import ConfigParser
from dataclasses import dataclass
from io import StringIO
from typing import TYPE_CHECKING, Any

from sanic import Request

from renku_data_services.app_config import logging
from renku_data_services.base_models.core import APIUser
from renku_data_services.connected_services.apispec_extras import RenkuTokens
from renku_data_services.connected_services.db import ConnectedServicesRepository
from renku_data_services.connected_services.models import ProviderKind
from renku_data_services.connected_services.oauth_http import (
    OAuthHttpClientFactory,
)
from renku_data_services.data_connectors.models import DataConnector, GlobalDataConnector
from renku_data_services.notebooks.config import NotebooksConfig

if TYPE_CHECKING:
    from renku_data_services.storage.models import RCloneConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True, eq=True, kw_only=True)
class _OAuth2ConfigPartial:
    """Partial configuration; contains OAuth2 fields."""

    token: str
    token_url: str


class DataSourceRepository:
    """Repository for checking session images with rich responses."""

    def __init__(
        self,
        nb_config: NotebooksConfig,
        connected_services_repo: ConnectedServicesRepository,
        oauth_client_factory: OAuthHttpClientFactory,
    ) -> None:
        self.nb_config = nb_config
        self.connected_services_repo = connected_services_repo
        self.oauth_client_factory = oauth_client_factory

    async def handle_configuration(
        self, request: Request, user: APIUser, data_connector: DataConnector | GlobalDataConnector
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
            request=request, user=user, data_connector=data_connector
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
        self, request: Request, user: APIUser, data_connector: DataConnector | GlobalDataConnector, config_data: str
    ) -> str | None:
        """Handles patching the configuration of a data connector when a session is resumed.

        This method updates the "token" and the "token_url" fields and no other part of the configuration.

        Returns either a new configuration (INI form) or None if the configuration should be left untouched.
        """
        # NOTE: do not handle global data connectors
        if data_connector.namespace is None:
            return None

        parser = ConfigParser(interpolation=None)
        try:
            parser.read_string(config_data)
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
            request=request, user=user, data_connector=data_connector
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
        self, request: Request, user: APIUser, data_connector: DataConnector
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
        if user.access_token and user.refresh_token:
            renku_tokens = RenkuTokens(
                access_token=user.access_token,
                refresh_token=user.refresh_token,
            )
            token_config["refresh_token"] = renku_tokens.encode()
        if token_set.expires_at_iso:
            token_config["expiry"] = token_set.expires_at_iso
        token = json.dumps(token_config)
        token_url = request.url_for("oauth2_connections.post_token_endpoint", connection_id=connection.id)
        return _OAuth2ConfigPartial(token=token, token_url=token_url)
