"""Tests for ActivityPub WebFinger functionality."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from ulid import ULID

from renku_data_services.activitypub.core import ActivityPubService
from renku_data_services.activitypub.db import ActivityPubRepository
from renku_data_services.activitypub import models


@pytest.mark.asyncio
async def test_discover_inbox_url_returns_string_or_none(mock_project_repo, mock_config):
    """Test that _discover_inbox_url returns a string or None."""
    # Create the service
    activitypub_repo = AsyncMock(spec=ActivityPubRepository)
    service = ActivityPubService(
        activitypub_repo=activitypub_repo,
        project_repo=mock_project_repo,
        config=mock_config,
    )

    # Mock the httpx.AsyncClient
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "links": [
            {
                "rel": "self",
                "type": "application/activity+json",
                "href": "https://mastodon.social/users/test",
            }
        ]
    }
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.return_value = mock_response

    # Mock the second response for the actor profile
    mock_actor_response = MagicMock()
    mock_actor_response.status_code = 200
    mock_actor_response.json.return_value = {
        "inbox": "https://mastodon.social/users/test/inbox"
    }
    mock_client.get.side_effect = [mock_response, mock_actor_response]

    # Test with a valid actor URI
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await service._discover_inbox_url("https://mastodon.social/users/test")
        assert isinstance(result, str)
        assert result == "https://mastodon.social/users/test/inbox"

    # Test with an invalid actor URI
    mock_client.get.side_effect = httpx.RequestError("Connection error")
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await service._discover_inbox_url("https://invalid.example.com/users/test")
        assert result is None


@pytest.mark.asyncio
async def test_discover_inbox_url_handles_json_types(mock_project_repo, mock_config):
    """Test that _discover_inbox_url correctly handles different JSON types for inbox URL."""
    # Create the service
    activitypub_repo = AsyncMock(spec=ActivityPubRepository)
    service = ActivityPubService(
        activitypub_repo=activitypub_repo,
        project_repo=mock_project_repo,
        config=mock_config,
    )

    # Mock the httpx.AsyncClient
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "links": [
            {
                "rel": "self",
                "type": "application/activity+json",
                "href": "https://mastodon.social/users/test",
            }
        ]
    }
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.return_value = mock_response

    # Test with a string inbox URL
    mock_actor_response = MagicMock()
    mock_actor_response.status_code = 200
    mock_actor_response.json.return_value = {
        "inbox": "https://mastodon.social/users/test/inbox"
    }
    mock_client.get.side_effect = [mock_response, mock_actor_response]

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await service._discover_inbox_url("https://mastodon.social/users/test")
        assert isinstance(result, str)
        assert result == "https://mastodon.social/users/test/inbox"

    # Test with a non-string inbox URL (e.g., a JSON object)
    mock_actor_response = MagicMock()
    mock_actor_response.status_code = 200
    mock_actor_response.json.return_value = {
        "inbox": {"url": "https://mastodon.social/users/test/inbox"}
    }
    mock_client.get.side_effect = [mock_response, mock_actor_response]

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await service._discover_inbox_url("https://mastodon.social/users/test")
        assert isinstance(result, str)
        assert "https://mastodon.social/users/test/inbox" in result

    # Test with a null inbox URL
    mock_actor_response = MagicMock()
    mock_actor_response.status_code = 200
    mock_actor_response.json.return_value = {
        "inbox": None
    }
    mock_client.get.side_effect = [mock_response, mock_actor_response]

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await service._discover_inbox_url("https://mastodon.social/users/test")
        assert result is None
