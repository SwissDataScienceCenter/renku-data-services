"""Database repo for secrets."""

from collections.abc import AsyncGenerator, Callable, Sequence
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from renku_data_services.base_api.auth import APIUser, only_authenticated
from renku_data_services.base_models.core import InternalServiceAdmin, ServiceAdminId
from renku_data_services.errors import errors
from renku_data_services.secrets.models import Secret
from renku_data_services.secrets.orm import SecretORM


class LowLevelUserSecretsRepo:
    """An adapter for accessing user secrets without encryption handling."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
    ) -> None:
        self.session_maker = session_maker

    @only_authenticated
    async def get_secrets_by_ids(self, requested_by: APIUser, secret_ids: list[ULID]) -> list[Secret]:
        """Get a specific user secrets from the database."""
        secret_ids_str = map(str, secret_ids)
        async with self.session_maker() as session:
            stmt = select(SecretORM).where(SecretORM.user_id == requested_by.id).where(SecretORM.id.in_(secret_ids_str))
            res = await session.execute(stmt)
            orms = res.scalars()
            return [orm.dump() for orm in orms]

    async def get_all_secrets_batched(
        self, requested_by: InternalServiceAdmin, batch_size: int = 100
    ) -> AsyncGenerator[Sequence[tuple[Secret, str]], None]:
        """Get secrets in batches.

        Only for internal use.
        """
        if requested_by.id != ServiceAdminId.secrets_rotation:
            raise errors.ProgrammingError(message="Only secrets_rotation admin is allowed to call this method.")
        offset = 0
        while True:
            async with self.session_maker() as session, session.begin():
                result = await session.execute(
                    select(SecretORM).limit(batch_size).offset(offset).order_by(SecretORM.id)
                )
                secrets = [(s.dump(), cast(str, s.user_id)) for s in result.scalars()]
                if len(secrets) == 0:
                    break

                yield secrets

                offset += batch_size

    async def update_secret_values(self, requested_by: InternalServiceAdmin, secrets: list[Secret]) -> None:
        """Update multiple secret values at once.

        Only for internal use.
        """
        if requested_by.id != ServiceAdminId.secrets_rotation:
            raise errors.ProgrammingError(message="Only secrets_rotation admin is allowed to call this method.")
        secret_dict = {s.id: s for s in secrets}

        async with self.session_maker() as session, session.begin():
            result = await session.scalars(select(SecretORM).where(SecretORM.id.in_(secret_dict.keys())))
            found_secrets = list(result)

            found_secret_ids = {s.id for s in found_secrets}
            if len(secret_dict) != len(found_secret_ids):
                raise errors.MissingResourceError(
                    message=f"Couldn't find secrets with ids: '{secret_dict.keys() - found_secret_ids}'"
                )

            for secret in found_secrets:
                new_secret = secret_dict[secret.id]

                secret.encrypted_value = new_secret.encrypted_value
                secret.encrypted_key = new_secret.encrypted_key
                secret.modification_date = datetime.now(UTC).replace(microsecond=0)

            await session.flush()
