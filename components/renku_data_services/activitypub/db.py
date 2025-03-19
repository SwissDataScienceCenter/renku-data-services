"""Adapters for ActivityPub database classes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Optional

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from sanic.log import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from renku_data_services import errors
from renku_data_services.activitypub import models, orm
from renku_data_services.base_models.core import APIUser
from renku_data_services.project.db import ProjectRepository
from renku_data_services.utils.core import with_db_transaction


class ActivityPubRepository:
    """Repository for ActivityPub."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        project_repo: ProjectRepository,
        config: models.ActivityPubConfig,
    ) -> None:
        self.session_maker = session_maker
        self.project_repo = project_repo
        self.config = config

    async def get_actor(self, actor_id: ULID) -> models.ActivityPubActor:
        """Get an actor by ID."""
        logger.info(f"Getting ActivityPub actor by ID {actor_id}")

        async with self.session_maker() as session:
            result = await session.execute(select(orm.ActivityPubActorORM).where(orm.ActivityPubActorORM.id == actor_id))
            actor_orm = result.scalar_one_or_none()

            if actor_orm is None:
                logger.warning(f"Actor with id '{actor_id}' not found")
                raise errors.MissingResourceError(message=f"Actor with id '{actor_id}' does not exist.")

            logger.info(f"Found actor {actor_id} with username '{actor_orm.username}'")
            return actor_orm.dump()

    async def get_actor_by_username(self, username: str) -> models.ActivityPubActor:
        """Get an actor by username."""
        logger.info(f"Getting ActivityPub actor by username '{username}'")

        async with self.session_maker() as session:
            result = await session.execute(
                select(orm.ActivityPubActorORM).where(orm.ActivityPubActorORM.username == username)
            )
            actor_orm = result.scalar_one_or_none()

            if actor_orm is None:
                logger.warning(f"Actor with username '{username}' not found")
                raise errors.MissingResourceError(message=f"Actor with username '{username}' does not exist.")

            logger.info(f"Found actor {actor_orm.id} with username '{username}'")
            return actor_orm.dump()

    async def get_project_actor(self, project_id: ULID) -> models.ActivityPubActor:
        """Get the actor for a project."""
        logger.info(f"Getting ActivityPub actor for project {project_id}")

        async with self.session_maker() as session:
            result = await session.execute(
                select(orm.ActivityPubActorORM).where(orm.ActivityPubActorORM.project_id == project_id)
            )
            actor_orm = result.scalar_one_or_none()

            if actor_orm is None:
                logger.warning(f"Actor for project '{project_id}' not found")
                raise errors.MissingResourceError(
                    message=f"Actor for project with id '{project_id}' does not exist."
                )

            logger.info(f"Found actor {actor_orm.id} for project {project_id}")
            return actor_orm.dump()

    @with_db_transaction
    async def create_actor(
        self, actor: models.UnsavedActivityPubActor, *, session: AsyncSession | None = None
    ) -> models.ActivityPubActor:
        """Create a new actor."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required")

        logger.info(f"Creating new ActivityPub actor with username '{actor.username}'")

        # Check if username is already taken
        result = await session.execute(
            select(orm.ActivityPubActorORM).where(orm.ActivityPubActorORM.username == actor.username)
        )
        existing_actor = result.scalar_one_or_none()
        if existing_actor is not None:
            logger.warning(f"Cannot create actor: Username '{actor.username}' already exists")
            raise errors.ConflictError(message=f"Actor with username '{actor.username}' already exists.")

        # Generate key pair for the actor
        logger.info(f"Generating RSA key pair for actor '{actor.username}'")
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")

        public_key_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

        # Create the actor
        actor_orm = orm.ActivityPubActorORM(
            username=actor.username,
            name=actor.name,
            summary=actor.summary,
            type=actor.type,
            user_id=actor.user_id,
            project_id=actor.project_id,
            private_key_pem=private_key_pem,
            public_key_pem=public_key_pem,
        )

        session.add(actor_orm)
        await session.flush()
        await session.refresh(actor_orm)

        logger.info(f"Successfully created ActivityPub actor with ID {actor_orm.id} and username '{actor.username}'")
        return actor_orm.dump()

    @with_db_transaction
    async def update_actor(
        self, actor_id: ULID, name: Optional[str] = None, summary: Optional[str] = None, *, session: AsyncSession | None = None
    ) -> models.ActivityPubActor:
        """Update an actor."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required")

        logger.info(f"Updating ActivityPub actor {actor_id}")

        result = await session.execute(select(orm.ActivityPubActorORM).where(orm.ActivityPubActorORM.id == actor_id))
        actor_orm = result.scalar_one_or_none()

        if actor_orm is None:
            logger.error(f"Cannot update actor: Actor with id '{actor_id}' does not exist")
            raise errors.MissingResourceError(message=f"Actor with id '{actor_id}' does not exist.")

        # Update fields
        changes = []
        if name is not None and name != actor_orm.name:
            logger.info(f"Updating actor {actor_id} name from '{actor_orm.name}' to '{name}'")
            actor_orm.name = name
            changes.append("name")
        if summary is not None and summary != actor_orm.summary:
            logger.info(f"Updating actor {actor_id} summary")
            actor_orm.summary = summary
            changes.append("summary")

        if not changes:
            logger.info(f"No changes to apply for actor {actor_id}")
            return actor_orm.dump()

        actor_orm.updated_at = datetime.now(UTC).replace(microsecond=0)

        await session.flush()
        await session.refresh(actor_orm)

        logger.info(f"Successfully updated actor {actor_id} ({', '.join(changes)})")
        return actor_orm.dump()

    @with_db_transaction
    async def delete_actor(self, actor_id: ULID, *, session: AsyncSession | None = None) -> None:
        """Delete an actor."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required")

        logger.info(f"Deleting ActivityPub actor {actor_id}")

        result = await session.execute(select(orm.ActivityPubActorORM).where(orm.ActivityPubActorORM.id == actor_id))
        actor_orm = result.scalar_one_or_none()

        if actor_orm is None:
            logger.info(f"Actor {actor_id} not found, nothing to delete")
            return

        await session.delete(actor_orm)
        logger.info(f"Successfully deleted actor {actor_id}")

    async def get_followers(self, actor_id: ULID) -> list[models.ActivityPubFollower]:
        """Get all followers of an actor."""
        logger.info(f"Getting followers for actor {actor_id}")

        async with self.session_maker() as session:
            result = await session.execute(
                select(orm.ActivityPubFollowerORM).where(orm.ActivityPubFollowerORM.actor_id == actor_id)
            )
            followers_orm = result.scalars().all()

            follower_count = len(followers_orm)
            accepted_count = sum(1 for f in followers_orm if f.accepted)

            logger.info(f"Found {follower_count} followers for actor {actor_id} ({accepted_count} accepted)")
            return [follower.dump() for follower in followers_orm]

    @with_db_transaction
    async def add_follower(
        self, follower: models.UnsavedActivityPubFollower, *, session: AsyncSession | None = None
    ) -> models.ActivityPubFollower:
        """Add a follower to an actor."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required")

        # Validate the actor_id
        if not follower.actor_id:
            logger.error("Cannot add follower: Actor ID is missing")
            raise errors.ProgrammingError(message="Actor ID is required to add a follower")

        logger.info(f"Adding follower {follower.follower_actor_uri} to actor {follower.actor_id}")

        # Check if the actor exists
        result = await session.execute(
            select(orm.ActivityPubActorORM).where(orm.ActivityPubActorORM.id == follower.actor_id)
        )
        actor_orm = result.scalar_one_or_none()
        if actor_orm is None:
            logger.error(f"Cannot add follower: Actor with id '{follower.actor_id}' does not exist")
            raise errors.MissingResourceError(message=f"Actor with id '{follower.actor_id}' does not exist.")

        # Refresh the actor_orm to ensure it's fully loaded
        await session.refresh(actor_orm)

        # Check if the follower already exists
        result = await session.execute(
            select(orm.ActivityPubFollowerORM)
            .where(orm.ActivityPubFollowerORM.actor_id == follower.actor_id)
            .where(orm.ActivityPubFollowerORM.follower_actor_uri == follower.follower_actor_uri)
        )
        existing_follower = result.scalar_one_or_none()
        if existing_follower is not None:
            if existing_follower.accepted == follower.accepted:
                logger.info(f"Follower {follower.follower_actor_uri} already exists with same acceptance status")
                return existing_follower.dump()

            # Update the acceptance status
            logger.info(f"Updating acceptance status for follower {follower.follower_actor_uri} to {follower.accepted}")
            existing_follower.accepted = follower.accepted
            existing_follower.updated_at = datetime.now(UTC).replace(microsecond=0)
            await session.flush()
            await session.refresh(existing_follower)
            return existing_follower.dump()

        # Create the follower using the ORM
        logger.info(f"Creating new follower record for {follower.follower_actor_uri}")
        follower_orm = orm.ActivityPubFollowerORM(
            actor_id=actor_orm.id,
            follower_actor_uri=follower.follower_actor_uri,
            accepted=follower.accepted,
            actor=actor_orm
        )

        await session.refresh(actor_orm)
        session.add(follower_orm)
        await session.flush()
        await session.refresh(follower_orm)

        logger.info(f"Successfully added follower {follower.follower_actor_uri} to actor {follower.actor_id}")
        return follower_orm.dump()

    @with_db_transaction
    async def remove_follower(
        self, actor_id: ULID, follower_actor_uri: str, *, session: AsyncSession | None = None
    ) -> None:
        """Remove a follower from an actor."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required")

        logger.info(f"Removing follower {follower_actor_uri} from actor {actor_id}")

        result = await session.execute(
            select(orm.ActivityPubFollowerORM)
            .where(orm.ActivityPubFollowerORM.actor_id == actor_id)
            .where(orm.ActivityPubFollowerORM.follower_actor_uri == follower_actor_uri)
        )
        follower_orm = result.scalar_one_or_none()

        if follower_orm is None:
            logger.info(f"Follower {follower_actor_uri} not found for actor {actor_id}, nothing to remove")
            return

        await session.delete(follower_orm)
        logger.info(f"Successfully removed follower {follower_actor_uri} from actor {actor_id}")

    async def create_project_actor(self, user: APIUser, project_id: ULID) -> models.ActivityPubActor:
        """Create an actor for a project."""
        # Get the project
        project = await self.project_repo.get_project(user=user, project_id=project_id)

        # Create a username for the project
        username = f"{project.namespace.slug}_{project.slug}"

        logger.info(f"Creating new ActivityPub actor for project {project_id} with username '{username}'")

        # Create the actor
        actor = models.UnsavedActivityPubActor(
            username=username,
            name=project.name,
            summary=project.description,
            type=models.ActorType.PROJECT,
            project_id=project_id,
        )

        created_actor = await self.create_actor(actor)
        logger.info(f"Successfully created ActivityPub actor {created_actor.id} for project {project_id}")
        return created_actor

    async def get_or_create_project_actor(self, user: APIUser, project_id: ULID) -> models.ActivityPubActor:
        """Get or create an actor for a project."""
        logger.info(f"Getting or creating ActivityPub actor for project {project_id}")
        try:
            actor = await self.get_project_actor(project_id=project_id)
            logger.info(f"Found existing ActivityPub actor {actor.id} for project {project_id}")
            return actor
        except errors.MissingResourceError:
            logger.info(f"No existing actor found for project {project_id}, creating new one")
            return await self.create_project_actor(user=user, project_id=project_id)

    async def update_project_actor(self, user: APIUser, project_id: ULID) -> models.ActivityPubActor:
        """Update an actor for a project."""
        logger.info(f"Updating ActivityPub actor for project {project_id}")

        # Get the project
        project = await self.project_repo.get_project(user=user, project_id=project_id)

        try:
            actor = await self.get_project_actor(project_id=project_id)
            logger.info(f"Found existing actor {actor.id} for project {project_id}, updating metadata")
            updated_actor = await self.update_actor(actor_id=actor.id, name=project.name, summary=project.description)
            logger.info(f"Successfully updated actor {actor.id} for project {project_id}")
            return updated_actor
        except errors.MissingResourceError:
            logger.info(f"No existing actor found for project {project_id}, creating new one")
            return await self.create_project_actor(user=user, project_id=project_id)
