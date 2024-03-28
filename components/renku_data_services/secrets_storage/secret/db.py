"""Adapters for secret database classes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.secrets_storage.secret import models
from renku_data_services.secrets_storage.secret import orm as schemas
from renku_data_services.utils.cryptography import encrypt_string


class SecretRepository:
    """Repository for secrets."""

    def __init__(self, session_maker: Callable[..., AsyncSession], encryption_key: bytes):
        self.session_maker = session_maker  # type: ignore[call-overload]
        self.encryption_key: bytes = encryption_key

    async def get_secrets(self, user: base_models.APIUser) -> list[models.Secret]:
        """Get all secrets from the database."""
        if not user.is_authenticated:
            raise  # TODO: Raise proper error

        async with self.session_maker() as session:
            user_id: str = user.id  # type: ignore
            stmt = select(schemas.SecretORM)
            stmt = stmt.where(schemas.SecretORM.user_id == user_id)
            stmt = stmt.order_by(schemas.SecretORM.name)
            result = await session.execute(stmt)
            secrets = result.scalars().all()

            return [s.dump(password=self.encryption_key, salt=user_id) for s in secrets]

    async def get_secret(self, user: base_models.APIUser, secret_id: str) -> models.Secret:
        """Get one secret from the database."""
        async with self.session_maker() as session:
            user_id: str = user.id  # type: ignore
            stmt = select(schemas.SecretORM)
            stmt = stmt.where(schemas.SecretORM.user_id == user_id)
            stmt = stmt.where(schemas.SecretORM.id == secret_id)
            result = await session.execute(stmt)
            secret_orm = result.scalars().first()

            if secret_orm is None:
                raise errors.MissingResourceError(
                    message=f"Secret with id '{secret_id}' does not exist or you do not have access to it."
                )

            return secret_orm.dump(password=self.encryption_key, salt=user_id)

    async def insert_secret(self, user: base_models.APIUser, secret: models.Secret) -> models.Secret:
        """Insert a new secret entry."""
        user_id: str = user.id  # type: ignore
        secret_orm = schemas.SecretORM.load(
            secret, user_id=user_id, password=self.encryption_key, salt=user_id
        )
        secret_orm.modification_date = datetime.now(timezone.utc).replace(microsecond=0)

        async with self.session_maker() as session, session.begin():
            session.add(secret_orm)

            secret = secret_orm.dump(password=self.encryption_key, salt=user_id)
            if secret.id is None:
                raise errors.BaseError(
                    detail="The created secret does not have an ID but it should."
                )

        return secret

    async def update_secret(self, user: base_models.APIUser, secret_id: str, **payload) -> models.Secret:
        """Update a secret."""
        async with self.session_maker() as session, session.begin():
            user_id: str = user.id  # type: ignore
            stmt = select(schemas.SecretORM)
            stmt = stmt.where(schemas.SecretORM.user_id == user_id)
            stmt = stmt.where(schemas.SecretORM.id == secret_id)
            result = await session.scalars(stmt)
            secret_orm = result.one_or_none()

            if secret_orm is None:
                raise errors.MissingResourceError(
                    message=f"Secret with id '{secret_id}' does not exist or you do not have access to it."
                )
            if "name" in payload:
                secret_orm.name = payload["name"]
            if "value" in payload:
                secret_orm.value = encrypt_string(
                    password=self.encryption_key, salt=user_id, data=payload["value"]
                )
            secret_orm.modification_date = datetime.now(timezone.utc).replace(
                microsecond=0
            )

            # NOTE: Triggers validation before the transaction saves data
            return secret_orm.dump(password=self.encryption_key, salt=user_id)

    async def delete_secret(self, user: base_models.APIUser, secret_id: str) -> None:
        """Delete a secret entry."""
        async with self.session_maker() as session, session.begin():
            stmt = select(schemas.SecretORM)
            stmt = stmt.where(schemas.SecretORM.user_id == user.id)
            stmt = stmt.where(schemas.SecretORM.id == secret_id)
            result = await session.scalars(stmt)
            secret_orm = result.one_or_none()

            if secret_orm is None:
                return

            await session.delete(secret_orm)
