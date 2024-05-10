"""Dummy Keycloak API."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from renku_data_services.users.models import KeycloakAdminEvent, KeycloakEvent


@dataclass
class DummyKeycloakAPI:
    """Dummy Keycloak API."""

    users: Iterable[dict[str, Any] | Exception] = field(default_factory=list)
    user_events: Iterable[dict[str, Any] | Exception] = field(default_factory=list)
    admin_events: Iterable[dict[str, Any] | Exception] = field(default_factory=list)
    user_roles: dict[str, list[str]] = field(default_factory=dict)

    def get_users(self) -> Iterable[dict[str, Any]]:
        """Get users."""
        for user in self.users:
            if isinstance(user, Exception):
                raise user
            yield user
        return

    def get_admin_events(
        self,
        start_date: date,
        end_date: date | None = None,
        event_types: list[KeycloakAdminEvent] | None = None,
    ) -> Iterable[dict[str, Any]]:
        """Get admin events."""
        event_types_ = event_types or [KeycloakAdminEvent.CREATE, KeycloakAdminEvent.UPDATE, KeycloakAdminEvent.DELETE]
        resource_types_ = ["USER"]
        for event in self.admin_events:
            if isinstance(event, Exception):
                raise event
            if (
                KeycloakAdminEvent(event["operationType"]) in event_types_
                and event["resourceType"] in resource_types_
            ):
                yield event
        return

    def get_user_events(
        self, start_date: date, end_date: date | None = None, event_types: list[KeycloakEvent] | None = None
    ) -> Iterable[dict[str, Any]]:
        """Get user events."""
        event_types_ = event_types or [KeycloakEvent.UPDATE_PROFILE, KeycloakEvent.REGISTER]
        for event in self.user_events:
            if isinstance(event, Exception):
                raise event
            if KeycloakEvent(event["type"]) in event_types_:
                yield event
        return

    def get_admin_users(self) -> Iterable[dict[str, Any]]:
        """Get the users with the renku admin role."""
        for user in self.users:
            if isinstance(user, Exception):
                raise user
            if user["id"] in self.user_roles and "renku-admin" in self.user_roles[user["id"]]:
                yield user
        return
