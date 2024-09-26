"""Business logic for storage."""

from datetime import datetime

from renku_data_services import errors
from renku_data_services.storage import models
from renku_data_services.utils.core import get_openbis_pat


async def storage_secrets_preparation(
    secrets: list[models.CloudStorageSecretUpsert],
    storage: models.CloudStorage,
    expiration_timestamp: datetime | None = None,
) -> tuple[list[models.CloudStorageSecretUpsert], datetime | None]:
    """Prepare the validated secrets so that they can be stored (long-term)."""
    if storage.storage_type == "openbis":
        try:
            (
                secrets[0].value,
                expiration_timestamp,
            ) = await get_openbis_pat(storage.configuration["host"], secrets[0].value)
        except Exception as e:
            raise errors.ProgrammingError(message=str(e)) from e

    return secrets, expiration_timestamp
