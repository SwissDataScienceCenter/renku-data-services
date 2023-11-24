"""Keycloak API."""
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, Iterator, List, cast

import requests  # type: ignore[import-untyped, import]
from requests.adapters import HTTPAdapter  # type: ignore[import-untyped, import]
from urllib3.util import Retry

from renku_data_services.users.models import KeycloakAdminEvent, KeycloakEvent


@dataclass
class KeycloakAPI:
    """Small wrapper around the Keycloak REST API."""

    # Example url requests
    # https://dev.renku.ch/auth/admin/realms/Renku/events?first=0&max=11&type=REGISTER&type=UPDATE_PROFILE&type=UPDATE_EMAIL
    # https://dev.renku.ch/auth/admin/realms/Renku/events?dateFrom=2023-11-10&first=0&max=11&type=REGISTER&type=UPDATE_PROFILE&type=UPDATE_EMAIL
    keycloak_url: str
    client_secret: str = field(repr=False)
    realm: str = "Renku"
    client_id: str = "renku"
    result_per_request_limit: int = 100
    _http_client: requests.Session = field(
        init=False, repr=False, default_factory=lambda: KeycloakAPI._get_http_client()
    )
    _access_token: str | None = field(repr=False, default=None, init=False)

    def __post_init__(self):
        self.keycloak_url = self.keycloak_url.rstrip("/")

    @staticmethod
    def _get_http_client() -> requests.Session:
        retry_strategy = Retry(
            total=5,
            backoff_factor=2,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session = requests.Session()
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _authenticate(self):
        self._access_token = "access_token"  # nosec: B105

    @property
    def _auth_headers(self) -> Dict[str, str]:
        if not self._access_token:
            self._authenticate()
        return {"Authorization": f"Bearer {self._access_token}"}

    def get_users(self) -> Iterator[Dict[str, Any]]:
        """Get all users from Keycloak."""
        url = self.keycloak_url + f"/admin/realms/{self.realm}/users"
        query_args = {
            "max": self.result_per_request_limit + 1,
        }
        first = 0
        res = self._http_client.get(url, params={**query_args, "first": first}, headers=self._auth_headers)
        if res.status_code == 401:
            self._authenticate()
            res = self._http_client.get(url, params={**query_args, "first": first}, headers=self._auth_headers)
        output = res.json()
        if not isinstance(output, list):
            raise ValueError("Received unexpected response from Keycloak for users")
        output = cast(List[Dict[str, Any]], output)
        yield from output
        if len(output) < self.result_per_request_limit + 1:
            return
        first += self.result_per_request_limit

    def get_user_events(
        self, start_date: date, end_date: date | None = None, event_types: List[KeycloakEvent] | None = None
    ) -> Iterator[Dict[str, Any]]:
        """Get user events from Keycloak."""
        url = self.keycloak_url + f"/admin/realms/{self.realm}/events"
        query_event_types = event_types or [
            KeycloakEvent.UPDATE_PROFILE,
            KeycloakEvent.REGISTER,
        ]
        query_args = {
            "dateFrom": start_date.isoformat(),
            "type": [e.value for e in query_event_types],
            "max": self.result_per_request_limit + 1,
        }
        if end_date:
            query_args["dateTo"] = end_date.isoformat()
        first = 0
        res = self._http_client.get(url, params={**query_args, "first": first}, headers=self._auth_headers)
        if res.status_code == 401:
            self._authenticate()
            res = self._http_client.get(url, params={**query_args, "first": first}, headers=self._auth_headers)
        output = res.json()
        if not isinstance(output, list):
            raise ValueError("Received unexpected response from Keycloak for events")
        output = cast(List[Dict[str, Any]], output)
        yield from output
        # TODO: What happens if the output is not a list
        if isinstance(output, list) and len(output) < self.result_per_request_limit + 1:
            return
        first += self.result_per_request_limit

    def get_admin_events(
        self, start_date: date, end_date: date | None = None, event_types: List[KeycloakAdminEvent] | None = None
    ) -> Iterator[Dict[str, Any]]:
        """Get admin events from Keycloak."""
        url = self.keycloak_url + f"/admin/realms/{self.realm}/admin-events"
        query_event_types = event_types or [
            KeycloakAdminEvent.CREATE,
            KeycloakAdminEvent.UPDATE,
            KeycloakAdminEvent.DELETE,
        ]
        query_args = {
            "dateFrom": start_date.isoformat(),
            "operationTypes": [e.value for e in query_event_types],
            "max": self.result_per_request_limit + 1,
            "resourceTypes": "USER",
        }
        if end_date:
            query_args["dateTo"] = end_date.isoformat()
        first = 0
        res = self._http_client.get(url, params={**query_args, "first": first}, headers=self._auth_headers)
        if res.status_code == 401:
            self._authenticate()
            res = self._http_client.get(url, params={**query_args, "first": first}, headers=self._auth_headers)
        output = res.json()
        if not isinstance(output, list):
            raise ValueError("Received unexpected response from Keycloak for events")
        output = cast(List[Dict[str, Any]], output)
        yield from output
        # TODO: What happens if the output is not a list
        if isinstance(output, list) and len(output) < self.result_per_request_limit + 1:
            return
        first += self.result_per_request_limit
