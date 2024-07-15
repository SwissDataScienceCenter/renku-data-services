"""Database repo for secrets."""

from collections.abc import AsyncGenerator, Callable, Sequence
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services.base_api.auth import APIUser, only_authenticated
from renku_data_services.base_models.core import InternalServiceAdmin, ServiceAdminId
from renku_data_services.errors import errors
from renku_data_services.secrets.models import Secret, SecretKind
from renku_data_services.secrets.orm import SecretORM


class UserSecretsRepo:
    """An adapter for accessing users secrets."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
    ) -> None:
        self.session_maker = session_maker

    @only_authenticated
    async def get_user_secrets(self, requested_by: APIUser, kind: SecretKind) -> list[Secret]:
        """Get all user's secrets from the database."""
        async with self.session_maker() as session:
            stmt = select(SecretORM).where(SecretORM.user_id == requested_by.id).where(SecretORM.kind == kind)
            res = await session.execute(stmt)
            orm = res.scalars().all()
            return [o.dump() for o in orm]

    @only_authenticated
    async def get_secret_by_id(self, requested_by: APIUser, secret_id: str) -> Secret | None:
        """Get a specific user secret from the database."""
        async with self.session_maker() as session:
            stmt = select(SecretORM).where(SecretORM.user_id == requested_by.id).where(SecretORM.id == secret_id)
            res = await session.execute(stmt)
            orm = res.scalar_one_or_none()
            if orm is None:
                return None
            return orm.dump()

    @only_authenticated
    async def get_secrets_by_ids(self, requested_by: APIUser, secret_ids: list[str]) -> list[Secret]:
        """Get a specific user secrets from the database."""
        async with self.session_maker() as session:
            stmt = select(SecretORM).where(SecretORM.user_id == requested_by.id).where(SecretORM.id.in_(secret_ids))
            res = await session.execute(stmt)
            orms = res.scalars()
            return [orm.dump() for orm in orms]

    @only_authenticated
    async def insert_secret(self, requested_by: APIUser, secret: Secret) -> Secret:
        """Insert a new secret."""

        async with self.session_maker() as session, session.begin():
            orm = SecretORM(
                name=secret.name,
                user_id=cast(str, requested_by.id),
                encrypted_value=secret.encrypted_value,
                encrypted_key=secret.encrypted_key,
                kind=secret.kind,
            )
            session.add(orm)

            try:
                await session.flush()
            except IntegrityError as err:
                if len(err.args) > 0 and "UniqueViolationError" in err.args[0]:
                    raise errors.ValidationError(
                        message="The name for the secret should be unique but it already exists",
                        detail="Please modify the name field and then retry",
                    )
                else:
                    raise
            return orm.dump()

    @only_authenticated
    async def update_secret(
        self, requested_by: APIUser, secret_id: str, encrypted_value: bytes, encrypted_key: bytes
    ) -> Secret:
        """Update a secret."""

        async with self.session_maker() as session, session.begin():
            result = await session.execute(
                select(SecretORM).where(SecretORM.id == secret_id).where(SecretORM.user_id == requested_by.id)
            )
            secret = result.scalar_one_or_none()
            if secret is None:
                raise errors.MissingResourceError(message=f"The secret with id '{secret_id}' cannot be found")

            secret.update(encrypted_value=encrypted_value, encrypted_key=encrypted_key)
        return secret.dump()

    @only_authenticated
    async def delete_secret(self, requested_by: APIUser, secret_id: str) -> None:
        """Delete a secret."""

        async with self.session_maker() as session, session.begin():
            result = await session.execute(
                select(SecretORM).where(SecretORM.id == secret_id).where(SecretORM.user_id == requested_by.id)
            )
            secret = result.scalar_one_or_none()
            if secret is None:
                return None

            await session.execute(delete(SecretORM).where(SecretORM.id == secret.id))

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

    async def update_secrets(self, requested_by: InternalServiceAdmin, secrets: list[Secret]) -> None:
        """Update multiple secrets.

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
