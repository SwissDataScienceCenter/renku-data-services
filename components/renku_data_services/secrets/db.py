"""Database repo for secrets."""

from __future__ import annotations

import asyncio
import random
import string
from collections.abc import AsyncGenerator, Callable, Sequence
from datetime import UTC, datetime
from typing import cast

from cryptography.hazmat.primitives.asymmetric import rsa
from prometheus_client import Counter, Enum
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from renku_data_services.base_api.auth import APIUser, only_authenticated
from renku_data_services.base_models.core import InternalServiceAdmin, ServiceAdminId, Slug
from renku_data_services.errors import errors
from renku_data_services.secrets.models import Secret, SecretKind, SecretPatch, UnsavedSecret
from renku_data_services.secrets.orm import SecretORM
from renku_data_services.users.db import UserRepo


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

    async def rotate_encryption_keys(
        self,
        requested_by: InternalServiceAdmin,
        new_key: rsa.RSAPrivateKey,
        old_key: rsa.RSAPrivateKey,
        batch_size: int = 100,
    ) -> None:
        """Rotate all secrets to a new private key.

        This method undoes the outer encryption and reencrypts with a new key, without touching the inner encryption.
        """
        processed_secrets_metrics = Counter(
            "secrets_rotation_count",
            "Number of secrets rotated",
        )
        running_metrics = Enum(
            "secrets_rotation_state", "State of secrets rotation", states=["running", "finished", "errored"]
        )
        running_metrics.state("running")
        try:
            async for batch in self.get_all_secrets_batched(requested_by, batch_size):
                updated_secrets = []
                for secret, user_id in batch:
                    new_secret = await secret.rotate_single_encryption_key(user_id, new_key, old_key)
                    # we need to sleep, otherwise the async scheduler will never yield to other tasks like requests
                    await asyncio.sleep(0.000001)
                    if new_secret is not None:
                        updated_secrets.append(new_secret)

                await self.update_secret_values(requested_by, updated_secrets)
                processed_secrets_metrics.inc(len(updated_secrets))
        except:
            running_metrics.state("errored")
            raise
        else:
            running_metrics.state("finished")


class UserSecretsRepo:
    """An adapter for accessing users secrets with encryption handling."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        low_level_repo: LowLevelUserSecretsRepo,
        user_repo: UserRepo,
        secret_service_public_key: rsa.RSAPublicKey,
    ) -> None:
        self.session_maker = session_maker
        self.low_level_repo = low_level_repo
        self.user_repo = user_repo
        self.secret_service_public_key = secret_service_public_key

    @only_authenticated
    async def get_user_secrets(self, requested_by: APIUser, kind: SecretKind) -> list[Secret]:
        """Get all user's secrets from the database."""
        async with self.session_maker() as session:
            stmt = select(SecretORM).where(SecretORM.user_id == requested_by.id).where(SecretORM.kind == kind)
            res = await session.execute(stmt)
            orm = res.scalars().all()
            return [o.dump() for o in orm]

    @only_authenticated
    async def get_secret_by_id(self, requested_by: APIUser, secret_id: ULID) -> Secret:
        """Get a specific user secret from the database."""
        async with self.session_maker() as session:
            stmt = select(SecretORM).where(SecretORM.user_id == requested_by.id).where(SecretORM.id == secret_id)
            res = await session.execute(stmt)
            orm = res.scalar_one_or_none()
            if not orm:
                raise errors.MissingResourceError(message=f"The secret with id {secret_id} cannot be found.")
            return orm.dump()

    async def insert_secret(self, requested_by: APIUser, secret: UnsavedSecret) -> Secret:
        """Insert a new secret."""
        if requested_by.id is None:
            raise errors.UnauthorizedError(message="You have to be authenticated to perform this operation.")

        default_filename = secret.default_filename
        if default_filename is None:
            suffix = "".join([random.choice(string.ascii_lowercase + string.digits) for _ in range(8)])  # nosec B311
            name_slug = Slug.from_name(secret.name).value
            default_filename = f"{name_slug[:200]}-{suffix}"

        encrypted_value, encrypted_key = await self.user_repo.encrypt_user_secret(
            requested_by=requested_by,
            secret_service_public_key=self.secret_service_public_key,
            secret_value=secret.secret_value,
        )

        async with self.session_maker() as session, session.begin():
            secret_orm = SecretORM(
                name=secret.name,
                default_filename=default_filename,
                user_id=requested_by.id,
                encrypted_value=encrypted_value,
                encrypted_key=encrypted_key,
                kind=secret.kind,
            )
            session.add(secret_orm)

            try:
                await session.flush()
            except IntegrityError as err:
                if len(err.args) > 0 and "UniqueViolationError" in err.args[0]:
                    raise errors.ValidationError(
                        message="The default_filename for the secret should be unique but it already exists",
                        detail="Please modify the default_filename field and then retry",
                    ) from None
                else:
                    raise
            return secret_orm.dump()

    @only_authenticated
    async def update_secret(self, requested_by: APIUser, secret_id: ULID, patch: SecretPatch) -> Secret:
        """Update a secret."""

        async with self.session_maker() as session, session.begin():
            result = await session.execute(
                select(SecretORM).where(SecretORM.id == secret_id).where(SecretORM.user_id == requested_by.id)
            )
            secret = result.scalar_one_or_none()
            if secret is None:
                raise errors.MissingResourceError(message=f"The secret with id '{secret_id}' cannot be found")

            if patch.name is not None:
                secret.name = patch.name
            if patch.default_filename is not None and patch.default_filename != secret.default_filename:
                existing_secret = await session.scalar(
                    select(SecretORM)
                    .where(SecretORM.user_id == requested_by.id)
                    .where(SecretORM.default_filename == patch.default_filename)
                )
                if existing_secret is not None:
                    raise errors.ConflictError(
                        message=f"A user secret with the default filename '{patch.default_filename}' already exists."
                    )
                secret.default_filename = patch.default_filename
            if patch.secret_value is not None:
                encrypted_value, encrypted_key = await self.user_repo.encrypt_user_secret(
                    requested_by=requested_by,
                    secret_service_public_key=self.secret_service_public_key,
                    secret_value=patch.secret_value,
                )
                secret.update(encrypted_value=encrypted_value, encrypted_key=encrypted_key)

            return secret.dump()

    @only_authenticated
    async def delete_secret(self, requested_by: APIUser, secret_id: ULID) -> None:
        """Delete a secret."""

        async with self.session_maker() as session, session.begin():
            result = await session.execute(
                select(SecretORM).where(SecretORM.id == secret_id).where(SecretORM.user_id == requested_by.id)
            )
            secret = result.scalar_one_or_none()
            if secret is None:
                return None

            await session.execute(delete(SecretORM).where(SecretORM.id == secret.id))
