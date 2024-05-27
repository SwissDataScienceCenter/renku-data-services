"""Shared utility functions."""

import functools
import os
import ssl
from collections.abc import Awaitable, Callable
from typing import Any, Concatenate, ParamSpec, Protocol, TypeVar

import httpx
from deepmerge import Merger
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, stop_after_delay, wait_fixed

from renku_data_services import errors


@retry(stop=(stop_after_attempt(20) | stop_after_delay(300)), wait=wait_fixed(2), reraise=True)
def oidc_discovery(url: str, realm: str) -> dict[str, Any]:
    """Get OIDC configuration."""
    url = f"{url}/realms/{realm}/.well-known/openid-configuration"
    res = httpx.get(url, verify=get_ssl_context())
    if res.status_code == 200:
        return res.json()
    raise errors.ConfigurationError(message=f"Cannot successfully do OIDC discovery with url {url}.")


@functools.lru_cache(1)
def get_ssl_context() -> ssl.SSLContext:
    """Get an SSL context supporting mounted custom certificates."""
    context = ssl.create_default_context()
    custom_cert_file = os.environ.get("SSL_CERT_FILE", None)
    if custom_cert_file:
        context.load_verify_locations(cafile=custom_cert_file)
    return context


def merge_api_specs(*args) -> dict[str, Any]:
    """Merges API spec files into a single one."""
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
        return merged_spec
    for to_merge in args[1:]:
        merger.merge(merged_spec, to_merge)

    return merged_spec


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
    async def transaction_wrapper(self: _WithSessionMaker, *args: _P.args, **kwargs: _P.kwargs):
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
