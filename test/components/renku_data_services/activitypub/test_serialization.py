"""Tests for ActivityPub serialization functionality."""

from datetime import UTC, datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pytest
from ulid import ULID

from renku_data_services.activitypub.core import ActivityPubService
from renku_data_services.activitypub.db import ActivityPubRepository
from renku_data_services.activitypub import models


@dataclass
class TestDataclass:
    """Test dataclass for serialization tests."""

    name: str
    value: int
    nested: Optional[Dict[str, Any]] = None
    context: Optional[str] = None


@pytest.fixture
def service(mock_project_repo, mock_config):
    """Create an ActivityPub service for testing."""
    activitypub_repo = ActivityPubRepository(
        session_maker=lambda: None,
        project_repo=mock_project_repo,
        config=mock_config,
    )
    return ActivityPubService(
        activitypub_repo=activitypub_repo,
        project_repo=mock_project_repo,
        config=mock_config,
    )


def test_to_dict_handles_basic_types(service):
    """Test that _to_dict correctly handles basic Python types."""
    # Test with a string
    assert service._to_dict("test") == "test"

    # Test with an integer
    assert service._to_dict(42) == 42

    # Test with a float
    assert service._to_dict(3.14) == 3.14

    # Test with a boolean
    assert service._to_dict(True) is True
    assert service._to_dict(False) is False

    # Test with None
    assert service._to_dict(None) is None


def test_to_dict_handles_complex_types(service):
    """Test that _to_dict correctly handles complex Python types."""
    # Test with a list
    assert service._to_dict([1, 2, 3]) == [1, 2, 3]

    # Test with a dictionary
    assert service._to_dict({"a": 1, "b": 2}) == {"a": 1, "b": 2}

    # Test with a nested structure
    complex_obj = {
        "name": "test",
        "values": [1, 2, 3],
        "nested": {
            "a": True,
            "b": None,
        }
    }
    assert service._to_dict(complex_obj) == complex_obj


def test_to_dict_handles_datetime(service):
    """Test that _to_dict correctly handles datetime objects."""
    # Create a datetime object
    dt = datetime(2025, 3, 20, 12, 34, 56, tzinfo=UTC)

    # Convert to dict
    result = service._to_dict(dt)

    # Verify the result is an ISO-formatted string
    assert isinstance(result, str)
    assert result == "2025-03-20T12:34:56+00:00"


def test_to_dict_handles_ulid(service):
    """Test that _to_dict correctly handles ULID objects."""
    # Create a ULID object
    ulid = ULID()

    # Convert to dict
    result = service._to_dict(ulid)

    # Verify the result is a string representation of the ULID
    assert isinstance(result, str)
    assert result == str(ulid)


def test_to_dict_handles_dataclasses(service):
    """Test that _to_dict correctly handles dataclass objects."""
    # Create a dataclass instance
    obj = TestDataclass(
        name="test",
        value=42,
        nested={"a": 1, "b": 2},
    )

    # Convert to dict
    result = service._to_dict(obj)

    # Verify the result
    assert isinstance(result, dict)
    assert result["name"] == "test"
    assert result["value"] == 42
    assert result["nested"] == {"a": 1, "b": 2}
    assert "context" not in result  # None values should be skipped


def test_to_dict_handles_context_field(service):
    """Test that _to_dict correctly handles the special 'context' field in dataclasses."""
    # Create a dataclass instance with a context field
    obj = TestDataclass(
        name="test",
        value=42,
        context="https://www.w3.org/ns/activitystreams",
    )

    # Convert to dict
    result = service._to_dict(obj)

    # Verify the result
    assert isinstance(result, dict)
    assert result["name"] == "test"
    assert result["value"] == 42
    assert "@context" in result  # context should be converted to @context
    assert result["@context"] == "https://www.w3.org/ns/activitystreams"


def test_to_dict_handles_activity_objects(service):
    """Test that _to_dict correctly handles Activity objects."""
    # Create an Activity object
    activity = models.Activity(
        id="https://example.com/activities/1",
        type=models.ActivityType.ACCEPT,
        actor="https://example.com/users/1",
        object={
            "type": models.ActivityType.FOLLOW,
            "actor": "https://mastodon.social/users/test",
            "object": "https://example.com/projects/1",
        },
        to=["https://mastodon.social/users/test"],
        published=datetime.now(UTC).isoformat(),
    )

    # Convert to dict
    result = service._to_dict(activity)

    # Verify the result
    assert isinstance(result, dict)
    assert result["id"] == activity.id
    assert result["type"] == activity.type
    assert result["actor"] == activity.actor
    assert isinstance(result["object"], dict)
    assert result["object"]["type"] == models.ActivityType.FOLLOW
    assert isinstance(result["to"], list)
    assert result["to"][0] == "https://mastodon.social/users/test"
    assert isinstance(result["published"], str)


def test_to_dict_handles_unknown_types(service):
    """Test that _to_dict correctly handles unknown types by converting them to strings."""
    # Create a custom class
    class CustomClass:
        def __str__(self):
            return "CustomClass"

    # Create an instance
    obj = CustomClass()

    # Convert to dict
    result = service._to_dict(obj)

    # Verify the result is a string
    assert isinstance(result, str)
    assert result == "CustomClass"
