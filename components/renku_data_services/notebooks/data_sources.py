"""Handling of data sources which require an OAuth2 connection."""

import json
from configparser import ConfigParser
from io import StringIO
from typing import Any

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

logger = logging.getLogger(__name__)


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
        """Ajusts the configuration of the input data connector if it requires an OAuth2 connection."""
        # NOTE: do not handle global data connectors
        if data_connector.namespace is None:
            return data_connector.storage.configuration

        provider_kind: ProviderKind | None = None
        match data_connector.storage.configuration["type"]:
            case "drive":
                provider_kind = ProviderKind.google
            case "dropbox":
                provider_kind = ProviderKind.dropbox
            case _:
                pass

        if provider_kind is None:
            return data_connector.storage.configuration

        configuration = data_connector.storage.configuration
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
        logger.info(f"Adjusting rclone configuration for data connector {str(data_connector.id)}.")
        if provider_kind == ProviderKind.google:
            configuration["scope"] = configuration.get("scope") or "drive"
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
        configuration["token"] = json.dumps(token_config)
        configuration["token_url"] = request.url_for(
            "oauth2_connections.post_token_endpoint", connection_id=connection.id
        )
        return configuration

    def is_patching_enabled(self, data_connector: DataConnector | GlobalDataConnector) -> bool:
        """Returns true iff the data connector can be patched."""
        # NOTE: do not handle global data connectors
        if data_connector.namespace is None:
            return False
        match data_connector.storage.configuration["type"]:
            case "drive":
                return True
            case "dropbox":
                return True
            case _:
                return False

    async def handle_patching_configuration(
        self, request: Request, user: APIUser, data_connector: DataConnector | GlobalDataConnector, config_data: str
    ) -> str | None:
        """Handles patching..."""
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
        logger.info(f"Got main section: {main_section}.")
        items = parser.items(main_section)
        logger.info(f"Got items: {items}.")
        configuration = dict(items)
        if configuration.get("type") != data_connector.storage.configuration.get("type"):
            logger.warning(
                f"Data connector type changed to {data_connector.storage.configuration.get("type")}, skipping!"
            )
            return None

        provider_kind: ProviderKind | None = None
        match data_connector.storage.configuration["type"]:
            case "drive":
                provider_kind = ProviderKind.google
            case "dropbox":
                provider_kind = ProviderKind.dropbox
            case _:
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
        logger.info(f"Adjusting rclone configuration for data connector {str(data_connector.id)}.")
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
        # configuration["token"] = json.dumps(token_config)
        # configuration["token_url"] = request.url_for(
        #     "oauth2_connections.post_token_endpoint", connection_id=connection.id
        # )
        # return configuration

        # for k, v in configuration.items():
        #     parser.set(name, k, _stringify(v))
        parser.set(main_section, "token", json.dumps(token_config))
        parser.set(
            main_section,
            "token_url",
            request.url_for("oauth2_connections.post_token_endpoint", connection_id=connection.id),
        )
        stringio = StringIO()
        parser.write(stringio)
        return stringio.getvalue()
