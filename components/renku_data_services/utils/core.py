"""Shared utility functions."""

import functools
import os
import ssl
from typing import Any, Callable, Protocol

from deepmerge import Merger
from sqlalchemy.ext.asyncio import AsyncSession


@functools.lru_cache(1)
def get_ssl_context():
    """Get an SSL context supporting mounted custom certificates."""
    context = ssl.create_default_context()
    custom_cert_file = os.environ.get("SSL_CERT_FILE", None)
    if custom_cert_file:
        context.load_verify_locations(cafile=custom_cert_file)
    return context


def merge_api_specs(*args):
    """Merges API spec files into a single one."""
    merger = Merger(
        type_strategies=[(list, "append_unique"), (dict, "merge"), (set, "union")],
        fallback_strategies=["override"],
        type_conflict_strategies=["override_if_not_empty"],
    )

    merged_spec: dict[str, Any]
    merged_spec = functools.reduce(merger.merge, args, dict())

    return merged_spec


class WithSessionMaker(Protocol):
    """Protocol for classes that wrap a session maker."""

    session_maker: Callable[..., AsyncSession]


def with_db_transaction(f):
    """Initializes a transaction and commits it on successful exit of the wrapped function."""

    @functools.wraps(f)
    async def transaction_wrapper(self: WithSessionMaker, *args, **kwargs):
        async with self.session_maker() as session, session.begin():
            return await f(self, session, *args, **kwargs)

    return transaction_wrapper
