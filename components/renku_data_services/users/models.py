"""Base models for users."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, NamedTuple

from pydantic import BaseModel, Field

from renku_data_services.app_config import logging
from renku_data_services.base_models import errors
from renku_data_services.namespace.models import UserNamespace

logger = logging.getLogger(__name__)


class KeycloakEvent(Enum):
    """The Keycloak user events that result from the user registering or updating their personal information."""

    REGISTER = "REGISTER"
    UPDATE_PROFILE = "UPDATE_PROFILE"


class KeycloakAdminEvent(Enum):
    """The Keycloak admin events used to keep users up to date."""

    DELETE = "DELETE"
    UPDATE = "UPDATE"
    CREATE = "CREATE"


@dataclass
class UserInfoFieldUpdate:
    """An update of a specific field of user information."""

    user_id: str
    timestamp_utc: datetime
    field_name: str
    new_value: str
    old_value: str | None = None

    @classmethod
    def from_json_user_events(cls, val: Iterable[dict[str, Any]]) -> list[UserInfoFieldUpdate]:
        """Generate a list of updates from a json response from Keycloak."""
        output: list[UserInfoFieldUpdate] = []
        for event in val:
            details = event.get("details")
            user_id = event.get("userId")
            timestamp_epoch = event.get("time")
            if not timestamp_epoch:
                logger.warning("Expected response from keycloak events to have a time field.")
                continue
            timestamp_utc = datetime.utcfromtimestamp(timestamp_epoch / 1000)
            if not details:
                logger.warning("Expected response from keycloak events to have a details field.")
                continue
            if not user_id:
                logger.warning("Expected response from keycloak events to have a userId field.")
                continue
            match event.get("type"):
                case KeycloakEvent.REGISTER.value:
                    first_name = details.get("first_name")
                    last_name = details.get("last_name")
                    email = details.get("email")
                    if email:
                        output.append(
                            UserInfoFieldUpdate(
                                field_name="email",
                                new_value=email,
                                timestamp_utc=timestamp_utc,
                                user_id=user_id,
                            )
                        )
                    if first_name:
                        output.append(
                            UserInfoFieldUpdate(
                                field_name="first_name",
                                new_value=first_name,
                                timestamp_utc=timestamp_utc,
                                user_id=user_id,
                            )
                        )
                    if last_name:
                        output.append(
                            UserInfoFieldUpdate(
                                field_name="last_name",
                                new_value=last_name,
                                timestamp_utc=timestamp_utc,
                                user_id=user_id,
                            )
                        )
                case KeycloakEvent.UPDATE_PROFILE.value:
                    first_name = details.get("updated_first_name")
                    last_name = details.get("updated_last_name")
                    email = details.get("updated_email")
                    if first_name:
                        old_value = details.get("previous_first_name")
                        output.append(
                            UserInfoFieldUpdate(
                                field_name="first_name",
                                new_value=first_name,
                                old_value=old_value,
                                timestamp_utc=timestamp_utc,
                                user_id=user_id,
                            )
                        )
                    if last_name:
                        old_value = details.get("previous_last_name")
                        output.append(
                            UserInfoFieldUpdate(
                                field_name="last_name",
                                new_value=last_name,
                                old_value=old_value,
                                timestamp_utc=timestamp_utc,
                                user_id=user_id,
                            )
                        )
                    if email:
                        old_value = details.get("previous_email")
                        output.append(
                            UserInfoFieldUpdate(
                                field_name="email",
                                new_value=email,
                                old_value=old_value,
                                timestamp_utc=timestamp_utc,
                                user_id=user_id,
                            )
                        )
                case _:
                    logger.warning(f"Skipping unknown event when parsing Keycloak user events: {event.get('type')}")
        return output

    @classmethod
    def from_json_admin_events(cls, val: Iterable[dict[str, Any]]) -> list[UserInfoFieldUpdate]:
        """Generate a list of updates from a json response from Keycloak."""
        output: list[UserInfoFieldUpdate] = []
        for event in val:
            timestamp_epoch = event.get("time")
            if not timestamp_epoch:
                logger.warning("Expected response from keycloak events to have a time field.")
                continue
            timestamp_utc = datetime.utcfromtimestamp(timestamp_epoch / 1000)
            resource = event.get("resourceType")
            if resource != "USER":
                continue
            operation = event.get("operationType")
            if not operation:
                logger.warning(f"Skipping unknown operation {operation}")
                continue
            resource_path = event.get("resourcePath")
            if not resource_path:
                logger.warning("Cannot find resource path in events response")
                continue
            user_id_match = re.match(r"^users/(.+)", resource_path)
            if not user_id_match:
                logger.warning("No match for user ID in resource path")
                continue
            user_id = user_id_match.group(1)
            if not isinstance(user_id, str) or user_id is None or len(user_id) == 0:
                logger.warning("Could not extract user ID from match in resource path")
                continue
            match operation:
                case KeycloakAdminEvent.CREATE.value | KeycloakAdminEvent.UPDATE.value:
                    payload = json.loads(event.get("representation", "{}"))
                    first_name = payload.get("firstName")
                    if first_name:
                        output.append(
                            UserInfoFieldUpdate(
                                field_name="first_name",
                                new_value=first_name,
                                timestamp_utc=timestamp_utc,
                                user_id=user_id,
                            )
                        )
                    last_name = payload.get("lastName")
                    if last_name:
                        output.append(
                            UserInfoFieldUpdate(
                                field_name="last_name",
                                new_value=last_name,
                                timestamp_utc=timestamp_utc,
                                user_id=user_id,
                            )
                        )
                    email = payload.get("email")
                    if email:
                        output.append(
                            UserInfoFieldUpdate(
                                field_name="email",
                                new_value=email,
                                timestamp_utc=timestamp_utc,
                                user_id=user_id,
                            )
                        )
                case KeycloakAdminEvent.DELETE.value:
                    output.append(
                        UserInfoFieldUpdate(
                            field_name="email",
                            new_value="",
                            timestamp_utc=timestamp_utc,
                            user_id=user_id,
                        )
                    )
                case _:
                    logger.warning(f"Skipping unknown admin event operation when parsing Keycloak events: {operation}")
        return output


@dataclass(eq=True, frozen=True, kw_only=True)
class UnsavedUserInfo:
    """Keycloak user."""

    id: str
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None

    @classmethod
    def from_kc_user_payload(cls, payload: dict[str, Any]) -> UnsavedUserInfo:
        """Create a user object from the user payload from the Keycloak admin API."""
        return UnsavedUserInfo(
            id=payload["id"],
            first_name=payload.get("firstName"),
            last_name=payload.get("lastName"),
            email=payload.get("email"),
        )

    def to_keycloak_dict(self) -> dict[str, Any]:
        """Create a payload that would have been created by Keycloak for this user, used only for testing."""

        return {
            "id": self.id,
            "createdTimestamp": int(datetime.now(UTC).timestamp() * 1000),
            "username": self.email,
            "enabled": True,
            "emailVerified": False,
            "firstName": self.first_name,
            "lastName": self.last_name,
            "email": self.email,
            "access": {
                "manageGroupMembership": True,
                "view": True,
                "mapRoles": True,
                "impersonate": True,
                "manage": True,
            },
            "bruteForceStatus": {
                "numFailures": 0,
                "disabled": False,
                "lastIPFailure": "n/a",
                "lastFailure": 0,
            },
        }


@dataclass(eq=True, frozen=True, kw_only=True)
class UserInfo(UnsavedUserInfo):
    """A tuple used to convey information about a user and their namespace."""

    namespace: UserNamespace

    def requires_update(self, current_user_info: UnsavedUserInfo) -> bool:
        """Returns true if the data self does not match the current_user_info."""
        if self.id != current_user_info.id:
            raise errors.ValidationError(message="Cannot check updates on two different users.")
        self_as_unsaved = UnsavedUserInfo(
            id=self.id,
            first_name=self.first_name,
            last_name=self.last_name,
            email=self.email,
        )
        return self_as_unsaved != current_user_info


@dataclass(frozen=True, eq=True, kw_only=True)
class UserPatch:
    """Model for changes requested on a user."""

    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None

    @classmethod
    def from_unsaved_user_info(cls, user: UnsavedUserInfo) -> UserPatch:
        """Create a user patch from a UnsavedUserInfo instance."""
        return UserPatch(
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
        )


@dataclass
class DeletedUser:
    """A user that was deleted from the database."""

    id: str


class UserInfoUpdate(NamedTuple):
    """Used to convey information about an update of a user or their namespace."""

    old: UserInfo | None
    new: UserInfo


class PinnedProjects(BaseModel):
    """Pinned projects model."""

    project_slugs: list[str] | None = None

    @classmethod
    def from_dict(cls, data: dict) -> PinnedProjects:
        """Create model from a dict object."""
        return cls(project_slugs=data.get("project_slugs"))


class UserPreferences(BaseModel):
    """User preferences model."""

    user_id: str = Field(min_length=3)
    pinned_projects: PinnedProjects
    show_project_migration_banner: bool = True
