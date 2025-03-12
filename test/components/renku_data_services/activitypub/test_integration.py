"""Integration tests for ActivityPub."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sanic import Sanic
from sanic.request import Request
from sanic.response import JSONResponse
from ulid import ULID

import renku_data_services.errors as errors
from renku_data_services.activitypub import models
from renku_data_services.activitypub.blueprints import ActivityPubBP
from renku_data_services.activitypub.core import ActivityPubService
from renku_data_services.activitypub.db import ActivityPubRepository
from renku_data_services.base_models.core import APIUser


@pytest.mark.asyncio
async def test_follow_project_flow(
    mock_session, mock_session_maker, mock_project_repo, mock_config, mock_actor, mock_actor_orm
):
    """Test the full flow of following a project."""
    # Configure the session to return an actor
    mock_session.execute.return_value.scalar_one_or_none.side_effect = [
        # First call: check if actor exists
        mock_actor_orm,
        # Second call: check if follower exists
        None,
    ]

    # Create the repository
    repo = ActivityPubRepository(
        session_maker=mock_session_maker,
        project_repo=mock_project_repo,
        config=mock_config,
    )

    # Create the service
    service = ActivityPubService(
        activitypub_repo=repo,
        project_repo=mock_project_repo,
        config=mock_config,
    )

    # Mock the _deliver_activity method
    service._deliver_activity = AsyncMock()

    # Create the blueprint
    blueprint = ActivityPubBP(
        name="activitypub",
        url_prefix="/api/data",
        activitypub_service=service,
        authenticator=MagicMock(),
        config=mock_config,
    )

    # Get the route handler
    _, _, handler = blueprint.project_inbox()

    # Create a mock request
    project_id = ULID()
    request = MagicMock(spec=Request)
    request.json = {
        "type": "Follow",
        "actor": "https://mastodon.social/users/test",
        "object": f"https://example.com/ap/projects/{project_id}",
    }

    # Call the handler
    response = await handler(request, project_id)

    # Verify the response
    assert response.status == 200

    # Verify the follower was added
    mock_session.add.assert_called_once()
    added_follower = mock_session.add.call_args[0][0]
    assert added_follower.actor_id == mock_actor.id
    assert added_follower.follower_actor_uri == "https://mastodon.social/users/test"
    assert added_follower.accepted is True

    # Verify the delivery was attempted
    service._deliver_activity.assert_called_once()
    actor_arg, activity_arg, inbox_url_arg = service._deliver_activity.call_args[0]
    assert actor_arg == mock_actor
    assert activity_arg.type == models.ActivityType.ACCEPT
    assert inbox_url_arg == "https://mastodon.social/users/test/inbox"


@pytest.mark.asyncio
async def test_unfollow_project_flow(
    mock_session, mock_session_maker, mock_project_repo, mock_config, mock_actor, mock_actor_orm, mock_follower_orm
):
    """Test the full flow of unfollowing a project."""
    # Configure the session to return an actor and a follower
    mock_session.execute.return_value.scalar_one_or_none.side_effect = [
        # First call: get_or_create_project_actor
        mock_actor_orm,
        # Second call: remove_follower
        mock_follower_orm,
    ]

    # Create the repository
    repo = ActivityPubRepository(
        session_maker=mock_session_maker,
        project_repo=mock_project_repo,
        config=mock_config,
    )

    # Create the service
    service = ActivityPubService(
        activitypub_repo=repo,
        project_repo=mock_project_repo,
        config=mock_config,
    )

    # Create the blueprint
    blueprint = ActivityPubBP(
        name="activitypub",
        url_prefix="/api/data",
        activitypub_service=service,
        authenticator=MagicMock(),
        config=mock_config,
    )

    # Get the route handler
    _, _, handler = blueprint.project_inbox()

    # Create a mock request
    project_id = ULID()
    request = MagicMock(spec=Request)
    request.json = {
        "type": "Undo",
        "actor": "https://mastodon.social/users/test",
        "object": {
            "type": "Follow",
            "actor": "https://mastodon.social/users/test",
            "object": f"https://example.com/ap/projects/{project_id}",
        },
    }

    # Call the handler
    response = await handler(request, project_id)

    # Verify the response
    assert response.status == 200

    # Verify the follower was removed
    mock_session.delete.assert_called_once_with(mock_follower_orm)


@pytest.mark.asyncio
async def test_get_project_actor(
    mock_session, mock_session_maker, mock_project_repo, mock_config, mock_actor, mock_actor_orm, mock_project
):
    """Test getting a project actor."""
    # Configure the session to return an actor
    mock_session.execute.return_value.scalar_one_or_none.return_value = mock_actor_orm

    # Create the repository
    repo = ActivityPubRepository(
        session_maker=mock_session_maker,
        project_repo=mock_project_repo,
        config=mock_config,
    )

    # Create the service
    service = ActivityPubService(
        activitypub_repo=repo,
        project_repo=mock_project_repo,
        config=mock_config,
    )

    # Create the blueprint
    blueprint = ActivityPubBP(
        name="activitypub",
        url_prefix="/api/data",
        activitypub_service=service,
        authenticator=MagicMock(),
        config=mock_config,
    )

    # Get the route handler
    _, _, handler = blueprint.get_project_actor()

    # Create a mock request
    project_id = mock_project.id
    request = MagicMock(spec=Request)
    user = APIUser(id="user1", is_admin=False)

    # Call the handler
    response = await handler(request, user, project_id)

    # Verify the response
    assert response.status == 200
    assert response.headers["Content-Type"] == "application/activity+json"

    # Verify the response content
    response_json = json.loads(response.body)
    assert response_json["id"] == f"{mock_config.base_url}/ap/projects/{project_id}"
    assert response_json["type"] == "Project"
    assert response_json["name"] == mock_project.name
    assert response_json["preferredUsername"] == mock_actor.username
    assert response_json["summary"] == mock_project.description
    assert response_json["inbox"] == f"{mock_config.base_url}/ap/projects/{project_id}/inbox"
    assert response_json["outbox"] == f"{mock_config.base_url}/ap/projects/{project_id}/outbox"
    assert response_json["followers"] == f"{mock_config.base_url}/ap/projects/{project_id}/followers"
    assert response_json["following"] == f"{mock_config.base_url}/ap/projects/{project_id}/following"
    assert response_json["publicKey"]["id"] == f"{mock_config.base_url}/ap/projects/{project_id}#main-key"
    assert response_json["publicKey"]["owner"] == f"{mock_config.base_url}/ap/projects/{project_id}"
    assert response_json["publicKey"]["publicKeyPem"] == mock_actor.public_key_pem


@pytest.mark.asyncio
async def test_get_project_followers(
    mock_session, mock_session_maker, mock_project_repo, mock_config, mock_actor, mock_actor_orm, mock_follower
):
    """Test getting project followers."""
    # Configure the session to return an actor and followers
    mock_session.execute.return_value.scalar_one_or_none.return_value = mock_actor_orm
    mock_session.execute.return_value.scalars.return_value.all.return_value = [
        mock_follower_orm for mock_follower_orm in [mock_follower]
    ]

    # Create the repository
    repo = ActivityPubRepository(
        session_maker=mock_session_maker,
        project_repo=mock_project_repo,
        config=mock_config,
    )

    # Create the service
    service = ActivityPubService(
        activitypub_repo=repo,
        project_repo=mock_project_repo,
        config=mock_config,
    )

    # Create the blueprint
    blueprint = ActivityPubBP(
        name="activitypub",
        url_prefix="/api/data",
        activitypub_service=service,
        authenticator=MagicMock(),
        config=mock_config,
    )

    # Get the route handler
    _, _, handler = blueprint.get_project_followers()

    # Create a mock request
    project_id = ULID()
    request = MagicMock(spec=Request)
    user = APIUser(id="user1", is_admin=False)

    # Call the handler
    response = await handler(request, user, project_id)

    # Verify the response
    assert response.status == 200

    # Verify the response content
    response_json = json.loads(response.body)
    assert "followers" in response_json
    assert len(response_json["followers"]) == 1
    assert response_json["followers"][0] == mock_follower.follower_actor_uri
