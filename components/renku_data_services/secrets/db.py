"""Database repo for secrets."""

import random
import string
from collections.abc import Callable

from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from renku_data_services.base_api.auth import APIUser, only_authenticated
from renku_data_services.base_models.core import Slug
from renku_data_services.errors import errors
from renku_data_services.secrets import low_level_db
from renku_data_services.secrets.core import encrypt_user_secret
from renku_data_services.secrets.models import NewSecret, Secret, SecretKind, SecretPatch
from renku_data_services.secrets.orm import SecretORM
from renku_data_services.users.db import UserRepo


class UserSecretsRepo:
    """An adapter for accessing users secrets with encryption handling."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        low_level_repo: low_level_db.LowLevelUserSecretsRepo,
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

    async def insert_secret(self, requested_by: APIUser, secret: NewSecret) -> Secret:
        """Insert a new secret."""
        if requested_by.id is None:
            raise errors.UnauthorizedError(message="You have to be authenticated to perform this operation.")

        default_filename = secret.default_filename
        if default_filename is None:
            suffix = "".join([random.choice(string.ascii_lowercase + string.digits) for _ in range(8)])  # nosec B311
            name_slug = Slug.from_name(secret.name).value
            default_filename = f"{name_slug[:200]}-{suffix}"

        encrypted_value, encrypted_key = await encrypt_user_secret(
            user_repo=self.user_repo,
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
                    )
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
                encrypted_value, encrypted_key = await encrypt_user_secret(
                    user_repo=self.user_repo,
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
