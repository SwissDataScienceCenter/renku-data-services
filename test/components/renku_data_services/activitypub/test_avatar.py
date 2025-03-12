"""Tests for ActivityPub project avatars."""

import json
from unittest.mock import MagicMock, patch

import pytest
from sanic import Sanic
from sanic.request import Request
from sanic.response import JSONResponse
from ulid import ULID

import renku_data_services.errors as errors
from renku_data_services.activitypub import models
from renku_data_services.activitypub.blueprints import ActivityPubBP
from renku_data_services.base_models.core import APIUser


@pytest.mark.asyncio
async def test_project_actor_has_avatar(mock_activity_service, mock_authenticator, mock_config, mock_actor, mock_project):
    """Test that the project actor has an avatar."""
    # Create the blueprint
    blueprint = ActivityPubBP(
        name="activitypub",
        url_prefix="/api/data",
        activitypub_service=mock_activity_service,
        authenticator=mock_authenticator,
        config=mock_config,
    )

    # Configure the mock service
    project_actor = models.ProjectActor.from_project(mock_project, mock_config.base_url, mock_config.domain)
    mock_activity_service.get_project_actor.return_value = project_actor
    mock_activity_service._to_dict.return_value = {
        "id": project_actor.id,
        "type": project_actor.type,
        "name": project_actor.name,
        "preferredUsername": project_actor.preferredUsername,
        "summary": project_actor.summary,
        "content": project_actor.content,
        "icon": {
            "type": "Image",
            "mediaType": "image/png",
            "url": f"https://www.gravatar.com/avatar/{str(mock_project.id)}?d=identicon&s=256"
        }
    }

    # Get the route handler
    _, _, handler = blueprint.get_project_actor()

    # Create a mock request with the necessary token field
    request = MagicMock(spec=Request)
    request.headers = {}
    mock_authenticator.token_field = "Authorization"

    # Set up the user that the authenticator will return
    user = APIUser(id="user1", is_admin=False)
    mock_authenticator.authenticate.return_value = user

    project_id = mock_project.id

    # Call the handler
    response = await handler(request, project_id)

    # Verify the response
    assert response.status == 200
    assert response.headers["Content-Type"] == "application/activity+json"

    # Verify the response content
    response_json = json.loads(response.body)

    # Check that the icon field exists and has the expected properties
    assert "icon" in response_json
    assert response_json["icon"]["type"] == "Image"
    assert response_json["icon"]["mediaType"] == "image/png"

    # Check that the avatar URL is based on the project ID
    expected_avatar_url = f"https://www.gravatar.com/avatar/{str(project_id)}?d=identicon&s=256"
    assert response_json["icon"]["url"] == expected_avatar_url
