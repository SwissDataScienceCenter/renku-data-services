"""Base models for users."""

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, NamedTuple

from pydantic import BaseModel, Field
from sanic.log import logger

from renku_data_services.namespace.models import Namespace


class KeycloakEvent(Enum):
    """The Keycloak user events that result from the user registering or updating their personal information."""

    REGISTER: str = "REGISTER"
    UPDATE_PROFILE: str = "UPDATE_PROFILE"


class KeycloakAdminEvent(Enum):
    """The Keycloak admin events used to keep users up to date."""

    DELETE: str = "DELETE"
    UPDATE: str = "UPDATE"
    CREATE: str = "CREATE"


@dataclass
class UserInfoFieldUpdate:
    """An update of a specific field of user information."""

    user_id: str
    timestamp_utc: datetime
    field_name: str
    new_value: str
    old_value: str | None = None

    @classmethod
    def from_json_user_events(self, val: Iterable[dict[str, Any]]) -> list["UserInfoFieldUpdate"]:
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
    def from_json_admin_events(self, val: Iterable[dict[str, Any]]) -> list["UserInfoFieldUpdate"]:
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
    def from_kc_user_payload(cls, payload: dict[str, Any]) -> "UnsavedUserInfo":
        """Create a user object from the user payload from the Keycloak admin API."""
        return UnsavedUserInfo(
            id=payload["id"],
            first_name=payload.get("firstName"),
            last_name=payload.get("lastName"),
            email=payload.get("email"),
        )

    def _to_keycloak_dict(self) -> dict[str, Any]:
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

    namespace: Namespace


class UserInfoUpdate(NamedTuple):
    """Used to convey information about an update of a user or their namespace."""

    old: UserInfo | None
    new: UserInfo


class PinnedProjects(BaseModel):
    """Pinned projects model."""

    project_slugs: list[str] | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "PinnedProjects":
        """Create model from a dict object."""
        return cls(project_slugs=data.get("project_slugs"))


class UserPreferences(BaseModel):
    """User preferences model."""

    user_id: str = Field(min_length=3)
    pinned_projects: PinnedProjects
