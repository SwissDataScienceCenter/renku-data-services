"""Tests for URL prefix in ActivityPub."""

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
async def test_url_prefix_in_actor_urls(
    mock_session, mock_session_maker, mock_project_repo, mock_actor, mock_actor_orm, mock_project
):
    """Test that the URL prefix is correctly included in the actor URLs."""
    # Configure the session to return an actor
    mock_session.execute.return_value.scalar_one_or_none.return_value = mock_actor_orm

    # Create a config with a URL prefix
    config = models.ActivityPubConfig(
        domain="example.com",
        base_url="https://example.com/api/data",  # Include the URL prefix
        admin_email="admin@example.com",
    )

    # Create the repository
    repo = ActivityPubRepository(
        session_maker=mock_session_maker,
        project_repo=mock_project_repo,
        config=config,
    )

    # Create the service
    service = ActivityPubService(
        activitypub_repo=repo,
        project_repo=mock_project_repo,
        config=config,
    )

    # Create the blueprint
    blueprint = ActivityPubBP(
        name="activitypub",
        url_prefix="/api/data",
        activitypub_service=service,
        authenticator=MagicMock(),
        config=config,
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

    # Check that all URLs include the URL prefix
    assert response_json["id"] == f"https://example.com/api/data/ap/projects/{project_id}"
    assert response_json["inbox"] == f"https://example.com/api/data/ap/projects/{project_id}/inbox"
    assert response_json["outbox"] == f"https://example.com/api/data/ap/projects/{project_id}/outbox"
    assert response_json["followers"] == f"https://example.com/api/data/ap/projects/{project_id}/followers"
    assert response_json["following"] == f"https://example.com/api/data/ap/projects/{project_id}/following"
    assert response_json["publicKey"]["id"] == f"https://example.com/api/data/ap/projects/{project_id}#main-key"
    assert response_json["publicKey"]["owner"] == f"https://example.com/api/data/ap/projects/{project_id}"

    # Check that the URL to the project page includes the URL prefix
    assert response_json["url"] == f"https://example.com/api/data/projects/{mock_project.namespace.slug}/{mock_project.slug}"


@pytest.mark.asyncio
async def test_url_prefix_in_webfinger_response(
    mock_session, mock_session_maker, mock_project_repo, mock_actor, mock_actor_orm, mock_project
):
    """Test that the URL prefix is correctly included in the WebFinger response."""
    # Configure the session to return an actor
    mock_session.execute.return_value.scalar_one_or_none.return_value = mock_actor_orm

    # Create a config with a URL prefix
    config = models.ActivityPubConfig(
        domain="example.com",
        base_url="https://example.com/api/data",  # Include the URL prefix
        admin_email="admin@example.com",
    )

    # Create the repository
    repo = ActivityPubRepository(
        session_maker=mock_session_maker,
        project_repo=mock_project_repo,
        config=config,
    )

    # Create the service
    service = ActivityPubService(
        activitypub_repo=repo,
        project_repo=mock_project_repo,
        config=config,
    )

    # Mock the get_project_actor_by_username method
    service.get_project_actor_by_username = AsyncMock()
    project_actor = models.ProjectActor(
        id=f"https://example.com/api/data/ap/projects/{mock_project.id}",
        name=mock_project.name,
        preferredUsername=mock_actor.username,
        summary=mock_project.description,
        content=mock_project.description,
        documentation=mock_project.documentation,
        attributedTo=f"https://example.com/api/data/ap/users/{mock_project.created_by}",
        to=["https://www.w3.org/ns/activitystreams#Public"],
        url=f"https://example.com/api/data/projects/{mock_project.namespace.slug}/{mock_project.slug}",
        published=mock_project.creation_date,
        updated=mock_project.updated_at,
        inbox=f"https://example.com/api/data/ap/projects/{mock_project.id}/inbox",
        outbox=f"https://example.com/api/data/ap/projects/{mock_project.id}/outbox",
        followers=f"https://example.com/api/data/ap/projects/{mock_project.id}/followers",
        following=f"https://example.com/api/data/ap/projects/{mock_project.id}/following",
        publicKey={
            "id": f"https://example.com/api/data/ap/projects/{mock_project.id}#main-key",
            "owner": f"https://example.com/api/data/ap/projects/{mock_project.id}",
            "publicKeyPem": mock_actor.public_key_pem,
        },
        keywords=mock_project.keywords,
        repositories=mock_project.repositories,
        visibility=mock_project.visibility.value,
        created_by=mock_project.created_by,
        creation_date=mock_project.creation_date,
        updated_at=mock_project.updated_at,
        type=models.ActorType.PROJECT,
    )
    service.get_project_actor_by_username.return_value = project_actor

    # Create the blueprint
    blueprint = ActivityPubBP(
        name="activitypub",
        url_prefix="/api/data",
        activitypub_service=service,
        authenticator=MagicMock(),
        config=config,
    )

    # Get the route handler
    _, _, handler = blueprint.webfinger()

    # Create a mock request
    request = MagicMock(spec=Request)
    request.args = {"resource": f"acct:{mock_actor.username}@example.com"}

    # Call the handler
    response = await handler(request)

    # Verify the response
    assert response.status == 200
    assert response.headers["Content-Type"] == "application/jrd+json"

    # Verify the response content
    response_json = json.loads(response.body)

    # Check that the URLs include the URL prefix
    assert response_json["aliases"] == [f"https://example.com/api/data/ap/projects/{mock_project.id}"]
    assert response_json["links"][0]["href"] == f"https://example.com/api/data/ap/projects/{mock_project.id}"


@pytest.mark.asyncio
async def test_url_prefix_in_host_meta_response(
    mock_session, mock_session_maker, mock_project_repo, mock_actor, mock_actor_orm, mock_project
):
    """Test that the URL prefix is correctly included in the host-meta response."""
    # Create a config with a URL prefix
    config = models.ActivityPubConfig(
        domain="example.com",
        base_url="https://example.com/api/data",  # Include the URL prefix
        admin_email="admin@example.com",
    )

    # Create the repository
    repo = ActivityPubRepository(
        session_maker=mock_session_maker,
        project_repo=mock_project_repo,
        config=config,
    )

    # Create the service
    service = ActivityPubService(
        activitypub_repo=repo,
        project_repo=mock_project_repo,
        config=config,
    )

    # Create the blueprint
    blueprint = ActivityPubBP(
        name="activitypub",
        url_prefix="/api/data",
        activitypub_service=service,
        authenticator=MagicMock(),
        config=config,
    )

    # Get the route handler
    _, _, handler = blueprint.host_meta()

    # Create a mock request
    request = MagicMock(spec=Request)

    # Call the handler
    response = await handler(request)

    # Verify the response
    assert response.status == 200
    assert response.headers["Content-Type"] == "application/xrd+xml"

    # Verify the response content
    response_text = response.body.decode("utf-8")

    # Check that the URL includes the URL prefix
    assert f'template="https://example.com/api/data/ap/webfinger?resource={{uri}}"' in response_text


@pytest.mark.asyncio
async def test_url_prefix_in_nodeinfo_response(
    mock_session, mock_session_maker, mock_project_repo, mock_actor, mock_actor_orm, mock_project
):
    """Test that the URL prefix is correctly included in the nodeinfo response."""
    # Create a config with a URL prefix
    config = models.ActivityPubConfig(
        domain="example.com",
        base_url="https://example.com/api/data",  # Include the URL prefix
        admin_email="admin@example.com",
    )

    # Create the repository
    repo = ActivityPubRepository(
        session_maker=mock_session_maker,
        project_repo=mock_project_repo,
        config=config,
    )

    # Create the service
    service = ActivityPubService(
        activitypub_repo=repo,
        project_repo=mock_project_repo,
        config=config,
    )

    # Create the blueprint
    blueprint = ActivityPubBP(
        name="activitypub",
        url_prefix="/api/data",
        activitypub_service=service,
        authenticator=MagicMock(),
        config=config,
    )

    # Get the route handler
    _, _, handler = blueprint.nodeinfo()

    # Create a mock request
    request = MagicMock(spec=Request)

    # Call the handler
    response = await handler(request)

    # Verify the response
    assert response.status == 200
    assert response.headers["Content-Type"] == "application/json"

    # Verify the response content
    response_json = json.loads(response.body)

    # Check that the URL includes the URL prefix
    assert response_json["links"][0]["href"] == "https://example.com/api/data/ap/nodeinfo/2.0"
