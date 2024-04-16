"""Database repo for secrets."""

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services.base_api.auth import APIUser, only_authenticated
from renku_data_services.errors import errors
from renku_data_services.secrets.models import Secret
from renku_data_services.secrets.orm import SecretORM


class UserSecretsRepo:
    """An adapter for accessing users secrets."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
    ):
        self.session_maker = session_maker

    @only_authenticated
    async def get_secrets(self, requested_by: APIUser) -> list[Secret]:
        """Get a specific user secret from the database."""
        async with self.session_maker() as session:
            stmt = select(SecretORM).where(SecretORM.user_id == requested_by.id)
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
        """Get a specific user secret from the database."""
        async with self.session_maker() as session:
            stmt = select(SecretORM).where(SecretORM.user_id == requested_by.id).where(SecretORM.id.in_(secret_ids))
            res = await session.execute(stmt)
            orms = res.scalars()
            return [orm.dump() for orm in orms]

    @only_authenticated
    async def insert_secret(self, requested_by: APIUser, secret: Secret) -> Secret | None:
        """Insert a new secret."""

        async with self.session_maker() as session, session.begin():
            modification_date = datetime.now(UTC).replace(microsecond=0)
            orm = SecretORM(
                name=secret.name,
                modification_date=modification_date,
                user_id=requested_by.id,
                encrypted_value=secret.encrypted_value,
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
            return orm.dump()

    @only_authenticated
    async def update_secret(self, requested_by: APIUser, secret_id: str, encrypted_value: bytes) -> Secret:
        """Update a secret."""

        async with self.session_maker() as session, session.begin():
            result = await session.execute(
                select(SecretORM).where(SecretORM.id == secret_id).where(SecretORM.user_id == requested_by.id)
            )
            secret = result.scalar_one_or_none()
            if secret is None:
                raise errors.MissingResourceError(message=f"The secret with id '{secret_id}' cannot be found")

            secret.encrypted_value = encrypted_value
            secret.modification_date = datetime.now(UTC).replace(microsecond=0)
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
