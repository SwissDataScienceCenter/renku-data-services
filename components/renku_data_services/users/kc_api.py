"""Keycloak API."""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, Iterable, List, Protocol, cast

import requests  # type: ignore[import-untyped, import]
from authlib.integrations.requests_client import OAuth2Session  # type: ignore[import-untyped, import]
from authlib.oauth2.rfc7523 import ClientSecretJWT  # type: ignore[import-untyped, import]
from requests.adapters import HTTPAdapter  # type: ignore[import-untyped, import]
from urllib3.util import Retry

from renku_data_services.users.models import KeycloakAdminEvent, KeycloakEvent


class IKeycloakAPI(Protocol):
    """Protocol for the Keycloak API."""

    def get_users(self) -> Iterable[Dict[str, Any]]:
        """Get all users."""
        ...

    def get_user_events(
        self, start_date: date, end_date: date | None = None, event_types: List[KeycloakEvent] | None = None
    ) -> Iterable[Dict[str, Any]]:
        """Get user events."""
        ...

    def get_admin_events(
        self, start_date: date, end_date: date | None = None, event_types: List[KeycloakAdminEvent] | None = None
    ) -> Iterable[Dict[str, Any]]:
        """Get admin events."""
        ...


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
    result_per_request_limit: int = 20
    _http_client: requests.Session = field(init=False, repr=False)

    def __post_init__(self):
        self.keycloak_url = self.keycloak_url.rstrip("/")
        retry_strategy = Retry(
            total=5,
            backoff_factor=2,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        token_endpoint = f"{self.keycloak_url}/realms/{self.realm}/protocol/openid-connect/token"
        session = OAuth2Session(
            client_id=self.client_id,
            client_secret=self.client_secret,
            token_endpoint_auth_method=ClientSecretJWT(token_endpoint),
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.fetch_token(
            url=token_endpoint,
            client_id=self.client_id,
            client_secret=self.client_secret,
            grant_type="client_credentials",
        )
        self._http_client = session

    def _paginated_requests_iter(self, path: str, query_args: Dict[str, Any] | None = None) -> Iterable[Dict[str, Any]]:
        url = self.keycloak_url + path
        req_query_args = deepcopy(query_args) if query_args else {}
        # Request one extra item to see if there is a need to request the next page or not
        req_query_args["max"] = self.result_per_request_limit + 1
        first = 0
        while True:
            res = self._http_client.get(url, params={**req_query_args, "first": first})
            output = res.json()
            if not isinstance(output, list):
                raise ValueError(f"Received unexpected response from Keycloak for path {path}")
            output = cast(List[Dict[str, Any]], output)
            if len(output) == 0:
                return
            # Do not display the extra item unless we are on the last page
            yield from output[:-1]
            if len(output) < self.result_per_request_limit + 1:
                # Since we got less elements than requested there are no more pages to request
                # Display the last element which was omitted above
                yield output[-1]
                return
            # Increment the offset so that the last (extra item) of the previous page is now first
            first += self.result_per_request_limit

    def get_users(self) -> Iterable[Dict[str, Any]]:
        """Get all users from Keycloak."""
        path = f"/admin/realms/{self.realm}/users"
        yield from self._paginated_requests_iter(path)

    def get_user_events(
        self, start_date: date, end_date: date | None = None, event_types: List[KeycloakEvent] | None = None
    ) -> Iterable[Dict[str, Any]]:
        """Get user events from Keycloak."""
        path = f"/admin/realms/{self.realm}/events"
        query_event_types = event_types or [
            KeycloakEvent.UPDATE_PROFILE,
            KeycloakEvent.REGISTER,
        ]
        query_args = {
            "dateFrom": start_date.isoformat(),
            "type": [e.value for e in query_event_types],
        }
        if end_date:
            query_args["dateTo"] = end_date.isoformat()
        yield from self._paginated_requests_iter(path, query_args)

    def get_admin_events(
        self, start_date: date, end_date: date | None = None, event_types: List[KeycloakAdminEvent] | None = None
    ) -> Iterable[Dict[str, Any]]:
        """Get admin events from Keycloak."""
        path = f"/admin/realms/{self.realm}/admin-events"
        query_event_types = event_types or [
            KeycloakAdminEvent.CREATE,
            KeycloakAdminEvent.UPDATE,
            KeycloakAdminEvent.DELETE,
        ]
        query_args = {
            "dateFrom": start_date.isoformat(),
            "operationTypes": [e.value for e in query_event_types],
            "resourceTypes": "USER",
        }
        if end_date:
            query_args["dateTo"] = end_date.isoformat()
        yield from self._paginated_requests_iter(path, query_args)
