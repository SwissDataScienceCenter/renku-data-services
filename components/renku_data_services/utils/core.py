"""Shared utility functions."""

import functools
import os
import ssl
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from json import JSONDecodeError
from typing import Any, Concatenate, ParamSpec, Protocol, TypeVar, cast
from zoneinfo import ZoneInfo

import httpx
from deepmerge import Merger
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services import errors
from renku_data_services.app_config import logging

logger = logging.getLogger(__name__)


@functools.lru_cache(1)
def get_ssl_context() -> ssl.SSLContext:
    """Get an SSL context supporting mounted custom certificates."""
    context = ssl.create_default_context()
    custom_cert_file = os.environ.get("SSL_CERT_FILE", None)
    if custom_cert_file:
        context.load_verify_locations(cafile=custom_cert_file)
    return context


def merge_api_specs(*args: list[dict[str, Any]]) -> dict[str, Any]:
    """Merges API spec files into a single one."""
    if any(not isinstance(arg, dict) for arg in args):
        raise errors.ConfigurationError(message="API Spec isn't of type 'dict'")
    merger = Merger(
        type_strategies=[(list, "append_unique"), (dict, "merge"), (set, "union")],
        fallback_strategies=["use_existing"],
        type_conflict_strategies=["use_existing"],
    )

    merged_spec: dict[str, Any] = dict()
    if len(args) == 0:
        return merged_spec
    merged_spec = args[0]
    if len(args) == 1:
        return cast(dict[str, Any], merged_spec)
    for to_merge in args[1:]:
        merger.merge(merged_spec, to_merge)

    return cast(dict[str, Any], merged_spec)


class WithSessionMaker(Protocol):
    """Protocol for classes that wrap a session maker."""

    def session_maker(self) -> AsyncSession:
        """Returns an async session."""
        ...


_P = ParamSpec("_P")
_T = TypeVar("_T")
_WithSessionMaker = TypeVar("_WithSessionMaker", bound=WithSessionMaker)


def with_db_transaction(
    f: Callable[Concatenate[_WithSessionMaker, _P], Awaitable[_T]],
) -> Callable[Concatenate[_WithSessionMaker, _P], Awaitable[_T]]:
    """Initializes a transaction and commits it on successful exit of the wrapped function."""

    @functools.wraps(f)
    async def transaction_wrapper(self: _WithSessionMaker, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        session_kwarg = kwargs.get("session")
        if "session" in kwargs and session_kwarg is not None and not isinstance(session_kwarg, AsyncSession):
            raise errors.ProgrammingError(
                message="The decorator that starts a DB transaction encountered an existing session "
                f"in the keyword arguments but the session is of an unexpected type {type(session_kwarg)}"
            )
        if session_kwarg is None:
            async with self.session_maker() as session, session.begin():
                kwargs["session"] = session
                return await f(self, *args, **kwargs)
        else:
            return await f(self, *args, **kwargs)

    return transaction_wrapper


def _get_openbis_url(openbis_host: str) -> str:
    return f"https://{openbis_host}/openbis/openbis/rmi-application-server-v3.json"


async def _get_openbis_session_token(openbis_host: str, login: dict[str, Any], timeout: int) -> str:
    async with httpx.AsyncClient(verify=get_ssl_context(), timeout=5) as client:
        response = await client.post(_get_openbis_url(openbis_host), json=login, timeout=timeout)
        if response.status_code != 200:
            raise errors.ThirdPartyAPIError(
                detail="OpenBIS responded with a non-200 status code when attempting to get a session token."
            )
        try:
            json: dict[str, str] = response.json()
        except JSONDecodeError as err:
            raise errors.ThirdPartyAPIError(
                detail="Did not receive a json-formatted output when attempting to get a session token from OpenBIS."
            ) from err
        if json.get("result") is None:
            raise errors.ThirdPartyAPIError(
                detail="The response from OpenBIS was parsed but it does not contain the exepected field(s) "
                "when attempting to get a session token."
            )
        return json["result"]


async def get_openbis_session_token_for_anonymous_user(
    openbis_host: str,
    timeout: int = 12,
) -> str:
    """Requests an openBIS session token for the anonymous user."""
    return await _get_openbis_session_token(
        openbis_host, {"method": "loginAsAnonymousUser", "params": [], "id": "1", "jsonrpc": "2.0"}, timeout
    )


async def get_openbis_session_token(
    openbis_host: str,
    username: str,
    password: str,
    timeout: int = 12,
) -> str:
    """Requests an openBIS session token with the user's login credentials."""
    return await _get_openbis_session_token(
        openbis_host, {"method": "login", "params": [username, password], "id": "2", "jsonrpc": "2.0"}, timeout
    )


async def get_openbis_pat(
    openbis_host: str,
    session_id: str,
    personal_access_token_session_name: str = "renku",
    minimum_validity_in_days: int = 2,
    timeout: int = 12,
) -> tuple[str, datetime]:
    """Requests an openBIS PAT with an openBIS session ID."""
    url = _get_openbis_url(openbis_host)

    async with httpx.AsyncClient(verify=get_ssl_context(), timeout=5) as client:
        get_server_information = {"method": "getServerInformation", "params": [session_id], "id": "2", "jsonrpc": "2.0"}
        response = await client.post(url, json=get_server_information, timeout=timeout)
        if response.status_code != 200:
            logger.error(
                f"Received a non-200 response, {response.status_code} from OpenBIS "
                f"for performing 'getServerInformation'. Reponse content: {response.text}"
            )
            raise errors.ThirdPartyAPIError(
                detail="OpenBIS responded with a non-200 status code when performing 'getServerInformation'."
            )
        try:
            json1: dict[str, dict[str, str]] = response.json()
        except JSONDecodeError as err:
            logger.error(
                f"Could not parse OpenBIS response for performing 'getServerInformation' into JSON. "
                f"Response content: {response.text}"
            )
            raise errors.ThirdPartyAPIError(
                detail="Could not parse OpenBIS response about server information into JSON."
            ) from err
        if "error" in json1:
            raise errors.ThirdPartyAPIError(
                detail=f"The response from OpenBIS for 'getServerInformation' contained errors: {json1['error']}."
            )
        if json1.get("result", {}).get("personal-access-tokens-max-validity-period") is None:
            logger.error(
                f"The response from OpenBIS for 'getServerInformation' did not contain the expected "
                "token validity period fields. "
                f"Response content: {response.text}"
            )
            raise errors.ThirdPartyAPIError(
                detail="The response from OpenBIS for 'getServerInformation' "
                "did not contain the expected token validity period."
            )
        personal_access_tokens_max_validity_period = int(json1["result"]["personal-access-tokens-max-validity-period"])
        valid_from = datetime.now(ZoneInfo("Europe/Berlin"))
        valid_to = valid_from + timedelta(seconds=personal_access_tokens_max_validity_period)
        validity_in_days = (valid_to - valid_from).days
        if validity_in_days < minimum_validity_in_days:
            raise errors.ThirdPartyAPIError(
                detail="The allowed validity of the personal access token from OpenBIS is shorter "
                f"than the required minimum validity of {minimum_validity_in_days} days"
            )
        create_personal_access_tokens = {
            "method": "createPersonalAccessTokens",
            "params": [
                session_id,
                {
                    "@type": "as.dto.pat.create.PersonalAccessTokenCreation",
                    "sessionName": personal_access_token_session_name,
                    "validFromDate": int(valid_from.timestamp() * 1000),
                    "validToDate": int(valid_to.timestamp() * 1000),
                },
            ],
            "id": "2",
            "jsonrpc": "2.0",
        }
        response = await client.post(url, json=create_personal_access_tokens, timeout=timeout)
        if response.status_code != 200:
            logger.error(
                "OpenBIS responded with a non-200 status code when creating a personal access token. "
                f"Status code: {response.status_code}, response content: {response.text}"
            )
            raise errors.ThirdPartyAPIError(
                detail="OpenBIS responded with a non-200 status code when creating a personal access token."
            )
        try:
            json2: dict[str, list[dict[str, str]]] = response.json()
        except JSONDecodeError as err:
            logger.error(
                "Could not parse OpenBIS response for creating a personal access token into JSON."
                f"Response content: {response.text}"
            )
            raise errors.ThirdPartyAPIError(
                detail="Could not parse OpenBIS response for creating personal access token into JSON."
            ) from err
        if (
            not isinstance(json2.get("result"), list)
            or len(json2["result"]) == 0
            or json2["result"][0].get("permId") is None
        ):
            logger.error(
                "The response from OpenBIS did not have the required 'result[0].permId' field in the response "
                "from creating a personal access token. "
                f"Response content: {response.text}"
            )
            raise errors.ThirdPartyAPIError(
                detail="The response from OpenBIS did not have the required 'result[0].permId' field in the response "
                "from creating a personal access token."
            )
        return json2["result"][0]["permId"], valid_to
