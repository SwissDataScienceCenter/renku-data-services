"""Shared utility functions."""

import functools
import os
import ssl
from collections.abc import Callable
from typing import Any, Protocol

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

    session_maker: Callable[..., AsyncSession]


def with_db_transaction(f):
    """Initializes a transaction and commits it on successful exit of the wrapped function."""

    @functools.wraps(f)
    async def transaction_wrapper(self: WithSessionMaker, *args, **kwargs):
        async with self.session_maker() as session, session.begin():
            return await f(self, session, *args, **kwargs)

    return transaction_wrapper
