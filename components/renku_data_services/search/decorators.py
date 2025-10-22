"""Decorators to support search integration."""

import functools
from collections.abc import Awaitable, Callable
from typing import Concatenate, ParamSpec, Protocol, TypeVar, cast

from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services.app_config import logging
from renku_data_services.data_connectors.models import (
    DataConnector,
    DataConnectorUpdate,
    DeletedDataConnector,
    GlobalDataConnector,
)
from renku_data_services.errors import errors
from renku_data_services.namespace.models import DeletedGroup, Group
from renku_data_services.project.models import DeletedProject, Project, ProjectUpdate
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.search.models import DeleteDoc
from renku_data_services.users.models import DeletedUser, UserInfo, UserInfoUpdate

logger = logging.getLogger(__name__)


class WithSearchUpdateRepo(Protocol):
    """The protocol required for a class to send messages to a message queue."""

    @property
    def search_updates_repo(self) -> SearchUpdatesRepo:
        """Returns the repository for updating search documents."""
        ...


_P = ParamSpec("_P")
_T = TypeVar("_T")
_WithSearchUpdateRepo = TypeVar("_WithSearchUpdateRepo", bound=WithSearchUpdateRepo)


def update_search_document(
    f: Callable[Concatenate[_WithSearchUpdateRepo, _P], Awaitable[_T]],
) -> Callable[Concatenate[_WithSearchUpdateRepo, _P], Awaitable[_T]]:
    """Calls the wrapped function and updates the search_update table with corresponding data."""

    @functools.wraps(f)
    async def func_wrapper(self: _WithSearchUpdateRepo, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        session = kwargs.get("session")
        if not isinstance(session, AsyncSession):
            raise errors.ProgrammingError(
                message="The decorator that populates the message queue expects a valid database session "
                f"in the keyword arguments instead it got {type(session)}."
            )
        result = await f(self, *args, **kwargs)
        if result is None:
            return result

        match result:
            case Project() as p:
                await self.search_updates_repo.upsert(p)

            case ProjectUpdate() as p:
                await self.search_updates_repo.upsert(p.new)

            case DeletedProject() as p:
                record = DeleteDoc.project(p.id)
                dcs = [DeleteDoc.data_connector(id) for id in p.data_connectors]
                await self.search_updates_repo.upsert(record)
                for d in dcs:
                    await self.search_updates_repo.upsert(d)

            case UserInfo() as u:
                await self.search_updates_repo.upsert(u)

            case UserInfoUpdate() as u:
                await self.search_updates_repo.upsert(u.new)

            case DeletedUser() as u:
                record = DeleteDoc.user(u.id)
                await self.search_updates_repo.upsert(record)

            case Group() as g:
                await self.search_updates_repo.upsert(g)

            case DeletedGroup() as g:
                record = DeleteDoc.group(g.id)
                await self.search_updates_repo.upsert(record)

            case DataConnector() as dc:
                await self.search_updates_repo.upsert(dc)

            case GlobalDataConnector() as dc:
                await self.search_updates_repo.upsert(dc)

            case DataConnectorUpdate() as dc:
                await self.search_updates_repo.upsert(dc.new)

            case DeletedDataConnector() as dc:
                record = DeleteDoc.data_connector(dc.id)
                await self.search_updates_repo.upsert(record)

            case list():
                match result:
                    case [UserInfo(), *_] as els:
                        users = cast(list[UserInfo], els)
                        for u in users:
                            await self.search_updates_repo.upsert(u)

            case _:
                error = errors.ProgrammingError(
                    message=f"Encountered unhandled search document of type '{result.__class__.__name__}'"
                )
                logger.error(error)

        return result

    return func_wrapper
