"""Shared utility functions."""

import functools
import datetime
import os
import ssl
from collections.abc import Awaitable, Callable
from typing import Any, Concatenate, ParamSpec, Protocol, TypeVar, cast

import httpx
from deepmerge import Merger
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, stop_after_delay, wait_fixed

from renku_data_services import errors


@retry(stop=(stop_after_attempt(20) | stop_after_delay(300)), wait=wait_fixed(2), reraise=True)
def oidc_discovery(url: str, realm: str) -> dict[str, Any]:
    """Get OIDC configuration."""
    url = f"{url}/realms/{realm}/.well-known/openid-configuration"
    res = httpx.get(url, verify=get_ssl_context(), timeout=5)
    if res.status_code == 200:
        return cast(dict[str, Any], res.json())
    raise errors.ConfigurationError(message=f"Cannot successfully do OIDC discovery with url {url}.")


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


async def get_openbis_pat(
    host: str,
    session_id: str,
    personal_access_token_session_name: str = "renku",
    minimum_validity_in_days: int = 2,
    timeout: int = 12,
) -> str:
    url = f"https://{host}/openbis/openbis/rmi-application-server-v3.json"

    get_server_information = {"method": "getServerInformation", "params": [session_id], "id": "2", "jsonrpc": "2.0"}

    async with httpx.AsyncClient(verify=get_ssl_context()) as client:
        response = await client.post(url, json=get_server_information, timeout=timeout)
        if response.status_code == 200:
            json1: dict[str, dict[str, str]] = response.json()
            personal_access_tokens_max_validity_period = int(
                json1["result"]["personal-access-tokens-max-validity-period"]
            )

            valid_from = datetime.datetime.now()
            valid_to = valid_from + datetime.timedelta(seconds=personal_access_tokens_max_validity_period)
            validity_in_days = (valid_to - valid_from).days
            if validity_in_days >= minimum_validity_in_days:
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

                if response.status_code == 200:
                    json2: dict[str, list[dict[str, str]]] = response.json()
                    return json2["result"][0]["permId"]
            else:
                raise Exception(
                    f"The maximum allowed validity period of a personal access token is less than {minimum_validity_in_days} days."
                )

        raise Exception("An openBIS personal access token related request failed.")
