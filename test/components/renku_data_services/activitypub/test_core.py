"""Tests for ActivityPub core functionality."""

from unittest.mock import AsyncMock, patch

import pytest
from ulid import ULID

import renku_data_services.errors as errors
from renku_data_services.activitypub import models
from renku_data_services.activitypub.core import ActivityPubService
from renku_data_services.activitypub.db import ActivityPubRepository
from renku_data_services.base_models.core import APIUser
from renku_data_services.project.db import ProjectRepository


@pytest.mark.asyncio
async def test_handle_follow(mock_project, mock_actor):
    """Test handling a follow request."""
    # Create mocks
    activitypub_repo = AsyncMock(spec=ActivityPubRepository)
    project_repo = AsyncMock(spec=ProjectRepository)
    config = models.ActivityPubConfig(
        domain="example.com",
        base_url="https://example.com",
        admin_email="admin@example.com",
    )

    # Configure mocks
    project_repo.get_project.return_value = mock_project
    activitypub_repo.get_or_create_project_actor.return_value = mock_actor
    activitypub_repo.add_follower.return_value = models.ActivityPubFollower(
        id=ULID(),
        actor_id=mock_actor.id,
        follower_actor_uri="https://mastodon.social/users/test",
        accepted=True,
        created_at="2025-03-03T12:00:00Z",
        updated_at="2025-03-03T12:00:00Z",
    )

    # Create service
    service = ActivityPubService(
        activitypub_repo=activitypub_repo,
        project_repo=project_repo,
        config=config,
    )

    # Mock the _deliver_activity method
    service._deliver_activity = AsyncMock()

    # Create test data
    user = APIUser(id="user1", is_admin=False)
    project_id = ULID()
    follower_actor_uri = "https://mastodon.social/users/test"

    # Call the method
    result = await service.handle_follow(user=user, project_id=project_id, follower_actor_uri=follower_actor_uri)

    # Verify the result
    assert result is not None
    assert result.type == models.ActivityType.ACCEPT
    assert result.actor == f"{config.base_url}/ap/projects/{project_id}"
    assert result.to == [follower_actor_uri]

    # Verify the mocks were called correctly
    activitypub_repo.get_or_create_project_actor.assert_called_once_with(user=user, project_id=project_id)
    activitypub_repo.add_follower.assert_called_once()
    follower = activitypub_repo.add_follower.call_args[0][0]
    assert follower.actor_id == mock_actor.id
    assert follower.follower_actor_uri == follower_actor_uri
    assert follower.accepted is True

    # Verify the delivery was attempted
    service._deliver_activity.assert_called_once()
    actor_arg, activity_arg, inbox_url_arg = service._deliver_activity.call_args[0]
    assert actor_arg == mock_actor
    assert activity_arg.type == models.ActivityType.ACCEPT
    assert inbox_url_arg == follower_actor_uri + "/inbox"


@pytest.mark.asyncio
async def test_handle_follow_missing_project():
    """Test handling a follow request for a missing project."""
    # Create mocks
    activitypub_repo = AsyncMock(spec=ActivityPubRepository)
    project_repo = AsyncMock(spec=ProjectRepository)
    config = models.ActivityPubConfig(
        domain="example.com",
        base_url="https://example.com",
        admin_email="admin@example.com",
    )

    # Configure mocks
    activitypub_repo.get_or_create_project_actor.side_effect = errors.MissingResourceError(message="Project not found")

    # Create service
    service = ActivityPubService(
        activitypub_repo=activitypub_repo,
        project_repo=project_repo,
        config=config,
    )

    # Mock the _deliver_activity method to avoid the error
    service._deliver_activity = AsyncMock()

    # Create test data
    user = APIUser(id="user1", is_admin=False)
    project_id = ULID()
    follower_actor_uri = "https://mastodon.social/users/test"

    # Call the method and verify it raises the expected exception
    with pytest.raises(errors.MissingResourceError, match="Project not found"):
        await service.handle_follow(user=user, project_id=project_id, follower_actor_uri=follower_actor_uri)

    # Verify the mocks were called correctly
    activitypub_repo.get_or_create_project_actor.assert_called_once_with(user=user, project_id=project_id)
    activitypub_repo.add_follower.assert_not_called()


@pytest.mark.asyncio
async def test_handle_unfollow(mock_actor):
    """Test handling an unfollow request."""
    # Create mocks
    activitypub_repo = AsyncMock(spec=ActivityPubRepository)
    project_repo = AsyncMock(spec=ProjectRepository)
    config = models.ActivityPubConfig(
        domain="example.com",
        base_url="https://example.com",
        admin_email="admin@example.com",
    )

    # Configure mocks
    activitypub_repo.get_or_create_project_actor.return_value = mock_actor

    # Create service
    service = ActivityPubService(
        activitypub_repo=activitypub_repo,
        project_repo=project_repo,
        config=config,
    )

    # Create test data
    user = APIUser(id="user1", is_admin=False)
    project_id = ULID()
    follower_actor_uri = "https://mastodon.social/users/test"

    # Call the method
    await service.handle_unfollow(user=user, project_id=project_id, follower_actor_uri=follower_actor_uri)

    # Verify the mocks were called correctly
    activitypub_repo.get_or_create_project_actor.assert_called_once_with(user=user, project_id=project_id)
    activitypub_repo.remove_follower.assert_called_once_with(
        actor_id=mock_actor.id, follower_actor_uri=follower_actor_uri
    )
