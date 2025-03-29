"""Tests for ActivityPub database repository."""

from datetime import UTC, datetime

import pytest
from ulid import ULID

import renku_data_services.errors as errors
from renku_data_services.activitypub import models, orm


@pytest.mark.asyncio
async def test_add_follower(mock_session, mock_session_maker, mock_project_repo, mock_config, mock_actor, mock_actor_orm):
    """Test adding a follower to an actor."""
    # Configure the session to return an actor
    mock_session.execute.return_value.scalar_one_or_none.side_effect = [
        # First call: check if actor exists
        mock_actor_orm,
        # Second call: check if follower exists
        None,
    ]

    # Create a follower
    follower = models.UnsavedActivityPubFollower(
        actor_id=mock_actor.id,
        follower_actor_uri="https://mastodon.social/users/test",
        accepted=True,
    )

    # Add the follower
    result = await mock_activitypub_repo.add_follower(follower, session=mock_session)

    # Verify the result
    assert result is not None
    assert result.actor_id == follower.actor_id
    assert result.follower_actor_uri == follower.follower_actor_uri
    assert result.accepted == follower.accepted

    # Verify the session was used correctly
    mock_session.add.assert_called_once()
    added_follower = mock_session.add.call_args[0][0]
    assert isinstance(added_follower, orm.ActivityPubFollowerORM)
    assert added_follower.actor_id == follower.actor_id
    assert added_follower.follower_actor_uri == follower.follower_actor_uri
    assert added_follower.accepted == follower.accepted

    mock_session.flush.assert_called_once()
    mock_session.refresh.assert_called_once_with(added_follower)


@pytest.mark.asyncio
async def test_add_follower_actor_not_found(mock_session, mock_activitypub_repo):
    """Test adding a follower to a non-existent actor."""
    # Configure the session to return no actor
    mock_session.execute.return_value.scalar_one_or_none.return_value = None

    # Create a follower
    actor_id = ULID()
    follower = models.UnsavedActivityPubFollower(
        actor_id=actor_id,
        follower_actor_uri="https://mastodon.social/users/test",
        accepted=True,
    )

    # Add the follower and verify it raises an exception
    with pytest.raises(errors.MissingResourceError, match=f"Actor with id '{actor_id}' does not exist."):
        await mock_activitypub_repo.add_follower(follower, session=mock_session)

    # Verify the session was used correctly
    mock_session.add.assert_not_called()
    mock_session.flush.assert_not_called()
    mock_session.refresh.assert_not_called()


@pytest.mark.asyncio
async def test_add_follower_already_exists(mock_session, mock_activitypub_repo, mock_actor, mock_actor_orm, mock_follower_orm):
    """Test adding a follower that already exists."""
    # Configure the session to return an actor and an existing follower
    mock_session.execute.return_value.scalar_one_or_none.side_effect = [
        # First call: check if actor exists
        mock_actor_orm,
        # Second call: check if follower exists
        mock_follower_orm,
    ]

    # Create a follower
    follower = models.UnsavedActivityPubFollower(
        actor_id=mock_actor.id,
        follower_actor_uri=mock_follower_orm.follower_actor_uri,
        accepted=mock_follower_orm.accepted,
    )

    # Add the follower
    result = await mock_activitypub_repo.add_follower(follower, session=mock_session)

    # Verify the result
    assert result is not None
    assert result.id == mock_follower_orm.id
    assert result.actor_id == follower.actor_id
    assert result.follower_actor_uri == follower.follower_actor_uri
    assert result.accepted == follower.accepted

    # Verify the session was used correctly
    mock_session.add.assert_not_called()
    mock_session.flush.assert_not_called()
    mock_session.refresh.assert_not_called()


@pytest.mark.asyncio
async def test_add_follower_update_acceptance(mock_session, mock_activitypub_repo, mock_actor, mock_actor_orm):
    """Test updating a follower's acceptance status."""
    # Create a follower
    follower_id = ULID()
    follower_uri = "https://mastodon.social/users/test"
    existing_follower = orm.ActivityPubFollowerORM(
        id=follower_id,
        actor_id=mock_actor.id,
        follower_actor_uri=follower_uri,
        accepted=False,  # Initially not accepted
        created_at=datetime.now(UTC).replace(microsecond=0),
        updated_at=datetime.now(UTC).replace(microsecond=0),
    )

    # Configure the session to return an actor and an existing follower
    mock_session.execute.return_value.scalar_one_or_none.side_effect = [
        # First call: check if actor exists
        mock_actor_orm,
        # Second call: check if follower exists
        existing_follower,
    ]

    # Create a follower with accepted=True
    follower = models.UnsavedActivityPubFollower(
        actor_id=mock_actor.id,
        follower_actor_uri=follower_uri,
        accepted=True,  # Now accepted
    )

    # Add the follower
    result = await mock_activitypub_repo.add_follower(follower, session=mock_session)

    # Verify the result
    assert result is not None
    assert result.id == follower_id
    assert result.actor_id == follower.actor_id
    assert result.follower_actor_uri == follower.follower_actor_uri
    assert result.accepted == follower.accepted  # Should be updated to True

    # Verify the existing follower was updated
    assert existing_follower.accepted is True

    # Verify the session was used correctly
    mock_session.add.assert_not_called()
    mock_session.flush.assert_called_once()
    mock_session.refresh.assert_called_once_with(existing_follower)


@pytest.mark.asyncio
async def test_remove_follower(mock_session, mock_activitypub_repo, mock_actor, mock_follower_orm):
    """Test removing a follower."""
    # Configure the session to return an existing follower
    mock_session.execute.return_value.scalar_one_or_none.return_value = mock_follower_orm

    # Remove the follower
    await mock_activitypub_repo.remove_follower(
        actor_id=mock_actor.id,
        follower_actor_uri=mock_follower_orm.follower_actor_uri,
        session=mock_session
    )

    # Verify the session was used correctly
    mock_session.delete.assert_called_once_with(mock_follower_orm)


@pytest.mark.asyncio
async def test_remove_follower_not_found(mock_session, mock_activitypub_repo):
    """Test removing a non-existent follower."""
    # Configure the session to return no follower
    mock_session.execute.return_value.scalar_one_or_none.return_value = None

    # Remove the follower
    actor_id = ULID()
    follower_uri = "https://mastodon.social/users/test"
    await mock_activitypub_repo.remove_follower(actor_id=actor_id, follower_actor_uri=follower_uri, session=mock_session)

    # Verify the session was used correctly
    mock_session.delete.assert_not_called()
