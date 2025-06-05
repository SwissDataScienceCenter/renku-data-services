"""Keycloak API."""

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date
from typing import Any, ClassVar, Protocol, cast

from authlib.integrations.requests_client import OAuth2Session
from authlib.oauth2.rfc7523 import ClientSecretJWT
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from renku_data_services.users.models import KeycloakAdminEvent, KeycloakEvent


class IKeycloakAPI(Protocol):
    """Protocol for the Keycloak API."""

    def get_users(self) -> Iterable[dict[str, Any]]:
        """Get all users."""
        ...

    def get_user_events(
        self, start_date: date, end_date: date | None = None, event_types: list[KeycloakEvent] | None = None
    ) -> Iterable[dict[str, Any]]:
        """Get user events."""
        ...

    def get_admin_events(
        self, start_date: date, end_date: date | None = None, event_types: list[KeycloakAdminEvent] | None = None
    ) -> Iterable[dict[str, Any]]:
        """Get admin events."""
        ...

    def get_admin_users(self) -> Iterable[dict[str, Any]]:
        """Get the users with the renku admin role."""
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
    _http_client: OAuth2Session = field(init=False, repr=False)
    admin_role: ClassVar[str] = "renku-admin"

    def __post_init__(self) -> None:
        self.keycloak_url = self.keycloak_url.rstrip("/")
        retry_strategy = Retry(
            total=5,
            backoff_factor=2,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        token_endpoint = f"{self.keycloak_url}/realms/{self.realm}/protocol/openid-connect/token"
        # NOTE: The data-service Keycloak client supports only the client_credentials grant
        # and without setting the grant below the token will not be re-fetched when it expires.
        session = OAuth2Session(
            client_id=self.client_id,
            client_secret=self.client_secret,
            token_endpoint_auth_method=ClientSecretJWT(token_endpoint),
            grant_type="client_credentials",
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.fetch_token(client_id=self.client_id, client_secret=self.client_secret, url=token_endpoint)
        self._http_client = session

    def _paginated_requests_iter(self, path: str, query_args: dict[str, Any] | None = None) -> Iterable[dict[str, Any]]:
        url = self.keycloak_url + path
        req_query_args = deepcopy(query_args) if query_args else {}
        # Request one extra item to see if there is a need to request the next page or not
        req_query_args["max"] = self.result_per_request_limit + 1
        first = 0
        while True:
            res = self._http_client.get(url, params={**req_query_args, "first": first})
            output = res.json()
            if not isinstance(output, list):
                raise ValueError(
                    f"Received unexpected response from Keycloak for path {path}, "
                    f"status code: {res.status_code}, body: {res.text}"
                )
            output = cast(list[dict[str, Any]], output)
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

    def get_users(self) -> Iterable[dict[str, Any]]:
        """Get all enabled users from Keycloak."""
        path = f"/admin/realms/{self.realm}/users"
        yield from filter(lambda user: user.get("enabled", False), self._paginated_requests_iter(path))

    def get_user_events(
        self, start_date: date, end_date: date | None = None, event_types: list[KeycloakEvent] | None = None
    ) -> Iterable[dict[str, Any]]:
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
        self, start_date: date, end_date: date | None = None, event_types: list[KeycloakAdminEvent] | None = None
    ) -> Iterable[dict[str, Any]]:
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

    def get_admin_users(self) -> Iterable[dict[str, Any]]:
        """Get the users that belong to the renku admin role."""
        path = f"/admin/realms/{self.realm}/roles/{self.admin_role}/users"
        yield from self._paginated_requests_iter(path)
