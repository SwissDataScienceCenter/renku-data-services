"""Message queue implementation for redis streams."""

import functools
from collections.abc import Awaitable, Callable
from typing import Concatenate, ParamSpec, Protocol, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services.errors import errors
from renku_data_services.namespace.models import DeletedGroup, Group
from renku_data_services.project.models import DeletedProject, Project, ProjectUpdate
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.users.models import DeletedUser, UserInfo, UserInfoUpdate


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
    """Initializes a transaction and commits it on successful exit of the wrapped function."""

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
                pass  # todo: oops, forgot that case 😅

            case UserInfo() as u:
                await self.search_updates_repo.upsert(u)

            case UserInfoUpdate() as u:
                await self.search_updates_repo.upsert(u.new)

            case DeletedUser() as u:
                pass  # todo: oops, forgot that case 😅

            case Group() as g:
                await self.search_updates_repo.upsert(g)

            case DeletedGroup() as g:
                pass  # todo: oops, forgot that case 😅

            case _:
                if isinstance(result, list):
                    for element in result:
                        match element:
                            case UserInfo() as u:
                                await self.search_updates_repo.upsert(u)

        return result

    return func_wrapper
