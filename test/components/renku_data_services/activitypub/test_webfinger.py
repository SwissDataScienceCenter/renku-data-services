"""Tests for ActivityPub WebFinger endpoint."""

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
async def test_webfinger_acct_uri(mock_activity_service, mock_authenticator, mock_config, mock_actor, mock_project):
    """Test the WebFinger endpoint with an acct: URI for a project."""
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
    mock_activity_service.get_project_actor_by_username.return_value = project_actor

    # Get the route handler
    _, _, handler = blueprint.webfinger()

    # Create a mock request
    # For projects, the username format is "{namespace_slug}_{project_slug}"
    # For example, if the namespace slug is "renku" and the project slug is "demo",
    # the username would be "renku_demo"
    username = f"{mock_project.namespace.slug}_{mock_project.slug}"
    request = MagicMock(spec=Request)
    request.args = {"resource": f"acct:{username}@{mock_config.domain}"}

    # Call the handler
    response = await handler(request)

    # Verify the response
    assert response.status == 200
    assert response.headers["Content-Type"] == "application/jrd+json"

    # Verify the response content
    response_json = json.loads(response.body)
    assert response_json["subject"] == f"acct:{username}@{mock_config.domain}"
    assert response_json["aliases"] == [project_actor.id]
    assert len(response_json["links"]) == 1
    assert response_json["links"][0]["rel"] == "self"
    assert response_json["links"][0]["type"] == "application/activity+json"
    assert response_json["links"][0]["href"] == project_actor.id

    # Verify the service was called correctly
    mock_activity_service.get_project_actor_by_username.assert_called_once_with(username=username)


@pytest.mark.asyncio
async def test_webfinger_https_uri(mock_activity_service, mock_authenticator, mock_config, mock_actor, mock_project):
    """Test the WebFinger endpoint with an https: URI for a project."""
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

    # Get the route handler
    _, _, handler = blueprint.webfinger()

    # Create a mock request
    project_id = mock_project.id
    request = MagicMock(spec=Request)
    request.args = {"resource": f"{mock_config.base_url}/ap/projects/{project_id}"}

    # Call the handler
    response = await handler(request)

    # Verify the response
    assert response.status == 200
    assert response.headers["Content-Type"] == "application/jrd+json"

    # Verify the response content
    response_json = json.loads(response.body)
    assert response_json["subject"] == f"{mock_config.base_url}/ap/projects/{project_id}"
    assert response_json["aliases"] == [f"acct:{project_actor.preferredUsername}@{mock_config.domain}"]
    assert len(response_json["links"]) == 1
    assert response_json["links"][0]["rel"] == "self"
    assert response_json["links"][0]["type"] == "application/activity+json"
    assert response_json["links"][0]["href"] == project_actor.id

    # Verify the service was called correctly
    mock_activity_service.get_project_actor.assert_called_once()
    args, kwargs = mock_activity_service.get_project_actor.call_args
    assert kwargs["user"].is_admin is True  # Should use an admin user
    assert kwargs["project_id"] == project_id


@pytest.mark.asyncio
async def test_webfinger_missing_resource(mock_activity_service, mock_authenticator, mock_config):
    """Test the WebFinger endpoint with a missing resource parameter."""
    # Create the blueprint
    blueprint = ActivityPubBP(
        name="activitypub",
        url_prefix="/api/data",
        activitypub_service=mock_activity_service,
        authenticator=mock_authenticator,
        config=mock_config,
    )

    # Get the route handler
    _, _, handler = blueprint.webfinger()

    # Create a mock request
    request = MagicMock(spec=Request)
    request.args = {}

    # Call the handler
    response = await handler(request)

    # Verify the response
    assert response.status == 400
    response_json = json.loads(response.body)
    assert response_json["error"] == "invalid_request"


@pytest.mark.asyncio
async def test_webfinger_invalid_resource(mock_activity_service, mock_authenticator, mock_config):
    """Test the WebFinger endpoint with an invalid resource parameter."""
    # Create the blueprint
    blueprint = ActivityPubBP(
        name="activitypub",
        url_prefix="/api/data",
        activitypub_service=mock_activity_service,
        authenticator=mock_authenticator,
        config=mock_config,
    )

    # Get the route handler
    _, _, handler = blueprint.webfinger()

    # Create a mock request
    request = MagicMock(spec=Request)
    request.args = {"resource": "invalid-resource"}

    # Call the handler
    response = await handler(request)

    # Verify the response
    assert response.status == 404
    response_json = json.loads(response.body)
    assert response_json["error"] == "not_found"


@pytest.mark.asyncio
async def test_webfinger_acct_not_found(mock_activity_service, mock_authenticator, mock_config):
    """Test the WebFinger endpoint with an acct: URI for a non-existent project."""
    # Create the blueprint
    blueprint = ActivityPubBP(
        name="activitypub",
        url_prefix="/api/data",
        activitypub_service=mock_activity_service,
        authenticator=mock_authenticator,
        config=mock_config,
    )

    # Configure the mock service
    mock_activity_service.get_project_actor_by_username.side_effect = errors.MissingResourceError(
        message="Actor not found"
    )

    # Get the route handler
    _, _, handler = blueprint.webfinger()

    # Create a mock request
    # For a non-existent project, we might try to look up something like "nonexistent_project"
    request = MagicMock(spec=Request)
    request.args = {"resource": f"acct:nonexistent_project@{mock_config.domain}"}

    # Call the handler
    response = await handler(request)

    # Verify the response
    assert response.status == 404
    response_json = json.loads(response.body)
    assert response_json["error"] == "not_found"

    # Verify the service was called
    mock_activity_service.get_project_actor_by_username.assert_called_once_with(username="nonexistent_project")


@pytest.mark.asyncio
async def test_webfinger_https_not_found(mock_activity_service, mock_authenticator, mock_config):
    """Test the WebFinger endpoint with an https: URI for a non-existent project."""
    # Create the blueprint
    blueprint = ActivityPubBP(
        name="activitypub",
        url_prefix="/api/data",
        activitypub_service=mock_activity_service,
        authenticator=mock_authenticator,
        config=mock_config,
    )

    # Configure the mock service
    mock_activity_service.get_project_actor.side_effect = errors.MissingResourceError(message="Project not found")

    # Get the route handler
    _, _, handler = blueprint.webfinger()

    # Create a mock request
    project_id = ULID()
    request = MagicMock(spec=Request)
    request.args = {"resource": f"{mock_config.base_url}/ap/projects/{project_id}"}

    # Call the handler
    response = await handler(request)

    # Verify the response
    assert response.status == 404
    response_json = json.loads(response.body)
    assert response_json["error"] == "not_found"

    # Verify the service was called
    mock_activity_service.get_project_actor.assert_called_once()
    args, kwargs = mock_activity_service.get_project_actor.call_args
    assert kwargs["user"].is_admin is True  # Should use an admin user
    assert kwargs["project_id"] == project_id
