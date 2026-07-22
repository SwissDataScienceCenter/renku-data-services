"""Constants for data connectors."""

from typing import Final

from renku_data_services.storage.constants import ENVIDAT_V1_PROVIDER, SCICAT_V1_PROVDER

ALLOWED_GLOBAL_DATA_CONNECTOR_PROVIDERS: Final[list[str]] = ["doi", ENVIDAT_V1_PROVIDER, SCICAT_V1_PROVDER]
