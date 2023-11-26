"""Dummy Keycloak API."""
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, Iterator, List

from renku_data_services.users.models import KeycloakAdminEvent, KeycloakEvent


def _dummy_users() -> List[Dict[str, Any]]:
    return [
        {
            "id": "af9b48d8-6537-4cd3-b550-c12f1f0be6db",
            "createdTimestamp": 1700872714072,
            "username": "bruce@wayne.com",
            "enabled": True,
            "emailVerified": False,
            "firstName": "Bruce",
            "lastName": "Wayne",
            "email": "bruce@wayne.com",
            "access": {
                "manageGroupMembership": True,
                "view": True,
                "mapRoles": True,
                "impersonate": True,
                "manage": True,
            },
            "bruteForceStatus": {"numFailures": 0, "disabled": False, "lastIPFailure": "n/a", "lastFailure": 0},
        },
        {
            "id": "44a168e4-3129-4937-82a2-816b1a31a336",
            "createdTimestamp": 1700924935723,
            "username": "john.doe@sdsc.ethz.ch",
            "enabled": True,
            "emailVerified": False,
            "firstName": "John",
            "lastName": "Doe",
            "email": "john.doe@sdsc.ethz.ch",
            "access": {
                "manageGroupMembership": True,
                "view": True,
                "mapRoles": True,
                "impersonate": True,
                "manage": True,
            },
            "bruteForceStatus": {"numFailures": 0, "disabled": False, "lastIPFailure": "n/a", "lastFailure": 0},
        },
    ]


def _dummy_user_events() -> List[Dict[str, Any]]:
    return [
        {
            "time": 1700124935723,
            "type": "UPDATE_PROFILE",
            "realmId": "61ae7898-50da-4088-a90e-f97002b1fb03",
            "clientId": "account",
            "userId": "af9b48d8-6537-4cd3-b550-c12f1f0be6db",
            "ipAddress": "192.168.0.128",
            "details": {"previous_first_name": "Bruce", "context": "ACCOUNT", "updated_first_name": "Batman"},
        },
        {
            "time": 1700224935723,
            "type": "UPDATE_PROFILE",
            "realmId": "61ae7898-50da-4088-a90e-f97002b1fb03",
            "clientId": "account",
            "userId": "44a168e4-3129-4937-82a2-816b1a31a336",
            "ipAddress": "192.168.0.128",
            "details": {
                "updated_email": "johnny@something.com",
                "updated_username": "johnny@something.com",
                "previous_email": "john.doe@sdsc.ethz.ch",
                "previous_username": "john.doe@sdsc.ethz.ch",
                "context": "ACCOUNT",
            },
        },
    ]


def _dummy_admin_events() -> List[Dict[str, Any]]:
    return [
        {
            "time": 1700670233597,
            "realmId": "61ae7898-50da-4088-a90e-f97002b1fb03",
            "authDetails": {
                "realmId": "61ae7898-50da-4088-a90e-f97002b1fb03",
                "clientId": "1cdaeb95-56dc-4fa7-b7ce-17bc5ea38979",
                "userId": "3aabcffa-32f6-427f-8204-3451eb80f566",
                "ipAddress": "192.168.0.128",
            },
            "operationType": "CREATE",
            "resourceType": "USER",
            "resourcePath": "users/2681edb2-6b57-45bb-ba71-4bf25e431c96",
            "representation": '{"enabled":true,"emailVerified":false,"firstName":"Robin",'
            '"lastName":"Superhero","email":"robin@wayne.com",'
            '"requiredActions":[],"groups":[]}',
        }
    ]


@dataclass
class DummyKeycloakAPI:
    """Dummy Keycloak API."""

    users: List[Dict[str, Any]] = field(default_factory=_dummy_users)
    user_events: List[Dict[str, Any]] = field(default_factory=_dummy_user_events)
    admin_update_events: List[Dict[str, Any]] = field(default_factory=_dummy_admin_events)
    admin_delete_events: List[Dict[str, Any]] = field(default_factory=list)

    def get_users(self) -> Iterator[Dict[str, Any]]:
        """Get users."""
        yield from self.users

    def get_admin_events(
        self, start_date: date, end_date: date | None = None, event_types: List[KeycloakAdminEvent] | None = None
    ) -> Iterator[Dict[str, Any]]:
        """Get admin events."""
        output_events = self.admin_update_events
        if KeycloakAdminEvent.DELETE in KeycloakAdminEvent:
            output_events = self.admin_delete_events
        yield from output_events

    def get_user_events(
        self, start_date: date, end_date: date | None = None, event_types: List[KeycloakEvent] | None = None
    ) -> Iterator[Dict[str, Any]]:
        """Get user events."""
        yield from self.user_events
