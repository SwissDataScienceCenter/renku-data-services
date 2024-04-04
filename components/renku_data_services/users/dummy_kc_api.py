"""Dummy Keycloak API."""
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from renku_data_services.users.models import KeycloakAdminEvent, KeycloakEvent


@dataclass
class DummyKeycloakAPI:
    """Dummy Keycloak API."""

    users: Iterable[dict[str, Any] | Exception] = field(default_factory=list)
    user_events: Iterable[dict[str, Any] | Exception] = field(default_factory=list)
    admin_update_events: Iterable[dict[str, Any] | Exception] = field(default_factory=list)
    admin_delete_events: Iterable[dict[str, Any] | Exception] = field(default_factory=list)

    def get_users(self) -> Iterable[dict[str, Any]]:
        """Get users."""
        users = self.users
        if not isinstance(users, Iterator):
            users = iter(users)
        while (elem := next(users, None)) is not None:
            if isinstance(elem, Exception):
                raise elem
            yield elem
        return

    def get_admin_events(
        self, start_date: date, end_date: date | None = None, event_types: list[KeycloakAdminEvent] | None = None
    ) -> Iterable[dict[str, Any]]:
        """Get admin events."""
        output_events = self.admin_update_events
        if isinstance(event_types, list) and KeycloakAdminEvent.DELETE in event_types:
            output_events = self.admin_delete_events
        if not isinstance(output_events, Iterator):
            output_events = iter(output_events)
        while (elem := next(output_events, None)) is not None:
            if isinstance(elem, Exception):
                raise elem
            yield elem
        return

    def get_user_events(
        self, start_date: date, end_date: date | None = None, event_types: list[KeycloakEvent] | None = None
    ) -> Iterable[dict[str, Any]]:
        """Get user events."""
        user_events = self.user_events
        if not isinstance(user_events, Iterator):
            user_events = iter(user_events)
        while (elem := next(user_events, None)) is not None:
            if isinstance(elem, Exception):
                raise elem
            yield elem
        return
