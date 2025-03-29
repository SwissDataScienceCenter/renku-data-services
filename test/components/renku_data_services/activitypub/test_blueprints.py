"""Tests for ActivityPub blueprints."""

from unittest.mock import MagicMock, patch

import pytest
from sanic import Sanic
from sanic.request import Request
from sanic.response import JSONResponse
from ulid import ULID

import renku_data_services.errors as errors
from renku_data_services.activitypub import models
from renku_data_services.activitypub.blueprints import ActivityPubBP


@pytest.mark.asyncio
async def test_project_inbox_follow(mock_activity_service, mock_authenticator, mock_config):
    """Test the project inbox endpoint with a Follow activity."""
    # Create the blueprint
    blueprint = ActivityPubBP(
        name="activitypub",
        url_prefix="/api/data",
        activitypub_service=mock_activity_service,
        authenticator=mock_authenticator,
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

    # Verify the service was called correctly
    mock_activity_service.handle_follow.assert_called_once()
    args, kwargs = mock_activity_service.handle_follow.call_args
    assert kwargs["user"].is_admin is True  # Should use an admin user
    assert kwargs["project_id"] == project_id
    assert kwargs["follower_actor_uri"] == "https://mastodon.social/users/test"


@pytest.mark.asyncio
async def test_project_inbox_undo_follow(mock_activity_service, mock_authenticator, mock_config):
    """Test the project inbox endpoint with an Undo of a Follow activity."""
    # Create the blueprint
    blueprint = ActivityPubBP(
        name="activitypub",
        url_prefix="/api/data",
        activitypub_service=mock_activity_service,
        authenticator=mock_authenticator,
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

    # Verify the service was called correctly
    mock_activity_service.handle_unfollow.assert_called_once()
    args, kwargs = mock_activity_service.handle_unfollow.call_args
    assert kwargs["user"].is_admin is True  # Should use an admin user
    assert kwargs["project_id"] == project_id
    assert kwargs["follower_actor_uri"] == "https://mastodon.social/users/test"


@pytest.mark.asyncio
async def test_project_inbox_empty_request(mock_activity_service, mock_authenticator, mock_config):
    """Test the project inbox endpoint with an empty request."""
    # Create the blueprint
    blueprint = ActivityPubBP(
        name="activitypub",
        url_prefix="/api/data",
        activitypub_service=mock_activity_service,
        authenticator=mock_authenticator,
        config=mock_config,
    )

    # Get the route handler
    _, _, handler = blueprint.project_inbox()

    # Create a mock request
    project_id = ULID()
    request = MagicMock(spec=Request)
    request.json = None

    # Call the handler
    response = await handler(request, project_id)

    # Verify the response
    assert response.status == 400
    assert response.json["error"] == "invalid_request"

    # Verify the service was not called
    mock_activity_service.handle_follow.assert_not_called()
    mock_activity_service.handle_unfollow.assert_not_called()


@pytest.mark.asyncio
async def test_project_inbox_missing_actor(mock_activity_service, mock_authenticator, mock_config):
    """Test the project inbox endpoint with a Follow activity missing the actor."""
    # Create the blueprint
    blueprint = ActivityPubBP(
        name="activitypub",
        url_prefix="/api/data",
        activitypub_service=mock_activity_service,
        authenticator=mock_authenticator,
        config=mock_config,
    )

    # Get the route handler
    _, _, handler = blueprint.project_inbox()

    # Create a mock request
    project_id = ULID()
    request = MagicMock(spec=Request)
    request.json = {
        "type": "Follow",
        "object": f"https://example.com/ap/projects/{project_id}",
    }

    # Call the handler
    response = await handler(request, project_id)

    # Verify the response
    assert response.status == 400
    assert response.json["error"] == "invalid_request"

    # Verify the service was not called
    mock_activity_service.handle_follow.assert_not_called()


@pytest.mark.asyncio
async def test_project_inbox_missing_project(mock_activity_service, mock_authenticator, mock_config):
    """Test the project inbox endpoint with a Follow activity for a missing project."""
    # Create the blueprint
    blueprint = ActivityPubBP(
        name="activitypub",
        url_prefix="/api/data",
        activitypub_service=mock_activity_service,
        authenticator=mock_authenticator,
        config=mock_config,
    )

    # Configure the service to raise an exception
    mock_activity_service.handle_follow.side_effect = errors.MissingResourceError(message="Project not found")

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
    assert response.status == 404
    assert response.json["error"] == "not_found"

    # Verify the service was called
    mock_activity_service.handle_follow.assert_called_once()
