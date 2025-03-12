"""Common fixtures for ActivityPub tests."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from renku_data_services.activitypub import models, orm
from renku_data_services.activitypub.core import ActivityPubService
from renku_data_services.activitypub.db import ActivityPubRepository
from renku_data_services.base_models.core import APIUser, Authenticator
from renku_data_services.project.db import ProjectRepository
from renku_data_services.project.models import Project, Namespace, Visibility


@pytest.fixture
def mock_project():
    """Create a mock project."""
    return Project(
        id=ULID(),
        name="Test Project",
        slug="test-project",
        description="A test project for ActivityPub",
        visibility=Visibility.PUBLIC,
        namespace=Namespace(
            id=ULID(),
            slug="test-namespace",
            name="Test Namespace",
            kind="user",
            created_by="user1",
            underlying_resource_id="user1",
        ),
        created_by="user1",
        creation_date="2025-03-03T12:00:00Z",
        updated_at="2025-03-03T12:00:00Z",
        documentation="Project documentation",
        keywords=["test", "activitypub"],
        repositories=["https://github.com/test/test-project"],
    )


@pytest.fixture
def mock_actor():
    """Create a mock ActivityPub actor."""
    return models.ActivityPubActor(
        id=ULID(),
        username="test-namespace_test-project",
        name="Test Project",
        summary="A test project for ActivityPub",
        type=models.ActorType.PROJECT,
        user_id="user1",
        project_id=ULID(),
        private_key_pem="-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7VJTUt9Us8cKj\nMzEfYyjiWA4R4/M2bS1GB4t7NXp98C3SC6dVMvDuictGeurT8jNbvJZHtCSuYEvu\nNMoSfm76oqFvAp8Gy0iz5sxjZmSnXyCdPEovGhLa0VzMaQ8s+CLOyS56YyCFGeJZ\n-----END PRIVATE KEY-----",
        public_key_pem="-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAu1SU1LfVLPHCozMxH2Mo\n4lgOEePzNm0tRgeLezV6ffAt0gunVTLw7onLRnrq0/IzW7yWR7QkrmBL7jTKEn5u\n+qKhbwKfBstIs+bMY2Zkp18gnTxKLxoS2tFczGkPLPgizskuemMghRniWQ==\n-----END PUBLIC KEY-----",
        created_at="2025-03-03T12:00:00Z",
        updated_at="2025-03-03T12:00:00Z",
    )


@pytest.fixture
def mock_actor_orm(mock_actor):
    """Create a mock ActivityPub actor ORM object."""
    actor_orm = orm.ActivityPubActorORM(
        username=mock_actor.username,
        name=mock_actor.name,
        summary=mock_actor.summary,
        type=mock_actor.type,
        user_id=mock_actor.user_id,
        project_id=mock_actor.project_id,
        private_key_pem=mock_actor.private_key_pem,
        public_key_pem=mock_actor.public_key_pem,
        created_at=datetime.fromisoformat(mock_actor.created_at),
        updated_at=datetime.fromisoformat(mock_actor.updated_at),
    )
    # Set the id directly on the instance
    actor_orm.id = mock_actor.id
    return actor_orm


@pytest.fixture
def mock_follower(mock_actor):
    """Create a mock ActivityPub follower."""
    return models.ActivityPubFollower(
        id=ULID(),
        actor_id=mock_actor.id,
        follower_actor_uri="https://mastodon.social/users/test",
        accepted=True,
        created_at="2025-03-03T12:00:00Z",
        updated_at="2025-03-03T12:00:00Z",
    )


@pytest.fixture
def mock_follower_orm(mock_actor):
    """Create a mock ActivityPub follower ORM object."""
    follower_id = ULID()
    follower_orm = orm.ActivityPubFollowerORM(
        actor_id=mock_actor.id,
        follower_actor_uri="https://mastodon.social/users/test",
        accepted=True,
        created_at=datetime.now(UTC).replace(microsecond=0),
        updated_at=datetime.now(UTC).replace(microsecond=0),
    )
    # Set the id directly on the instance
    follower_orm.id = follower_id
    return follower_orm


@pytest.fixture
def mock_session():
    """Create a mock SQLAlchemy session."""
    session = AsyncMock(spec=AsyncSession)

    # Configure the session to return results
    session.execute.return_value.scalar_one_or_none.return_value = None

    return session


@pytest.fixture
def mock_session_maker(mock_session):
    """Create a mock session maker."""
    session_maker = MagicMock()
    session_maker.return_value.__aenter__.return_value = mock_session
    return session_maker


@pytest.fixture
def mock_project_repo(mock_project):
    """Create a mock project repository."""
    project_repo = AsyncMock(spec=ProjectRepository)
    project_repo.get_project.return_value = mock_project
    return project_repo


@pytest.fixture
def mock_config():
    """Create a mock ActivityPub config."""
    return models.ActivityPubConfig(
        domain="example.com",
        base_url="https://example.com",
        admin_email="admin@example.com",
    )


@pytest.fixture
def mock_activity_service(mock_project_repo, mock_config):
    """Create a mock ActivityPub service."""
    service = AsyncMock(spec=ActivityPubService)

    # Configure the service to return an Accept activity
    activity = models.Activity(
        id=f"https://example.com/ap/projects/{ULID()}/activities/{ULID()}",
        type=models.ActivityType.ACCEPT,
        actor=f"https://example.com/ap/projects/{ULID()}",
        object={
            "type": models.ActivityType.FOLLOW,
            "actor": "https://mastodon.social/users/test",
            "object": f"https://example.com/ap/projects/{ULID()}",
        },
        to=["https://mastodon.social/users/test"],
        published="2025-03-03T12:00:00Z",
    )
    service.handle_follow.return_value = activity

    # Configure the _to_dict method to return a dictionary
    service._to_dict.return_value = {
        "id": activity.id,
        "type": activity.type,
        "actor": activity.actor,
        "object": activity.object,
        "to": activity.to,
        "published": activity.published,
    }

    return service


@pytest.fixture
def mock_authenticator():
    """Create a mock authenticator."""
    authenticator = AsyncMock(spec=Authenticator)

    # Configure the authenticator to return a user
    user = APIUser(id="user1", is_admin=False)
    authenticator.authenticate.return_value = user

    return authenticator


@pytest.fixture
def mock_activitypub_repo(mock_session_maker, mock_project_repo, mock_config):
    """Create a mock ActivityPub repository."""
    return ActivityPubRepository(
        session_maker=mock_session_maker,
        project_repo=mock_project_repo,
        config=mock_config,
    )
