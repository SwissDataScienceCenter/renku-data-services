"""Classes and decorators used for paginating long responses."""

from collections.abc import Callable, Coroutine, Sequence
from functools import wraps
from math import ceil
from typing import Any, Concatenate, NamedTuple, ParamSpec, TypeVar, cast

from sanic import Request, json
from sanic.response import JSONResponse
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services import errors


class PaginationRequest(NamedTuple):
    """Request for a paginated response."""

    page: int
    per_page: int

    def __post_init__(self) -> None:
        # NOTE: Postgres will fail if a value higher than what can fit in signed int64 is present in the query
        if self.page > 2**63 - 1:
            raise errors.ValidationError(message="Pagination parameter 'page' is too large")

    @property
    def offset(self) -> int:
        """Calculate an item offset required for pagination."""
        output = (self.page - 1) * self.per_page
        # NOTE: Postgres will fail if a value higher than what can fit in signed int64 is present in the query
        if output > 2**63 - 1:
            raise errors.ValidationError(
                message="Calculated pagination offset value is too large because "
                "the pagination parameter 'page' in the request is too large"
            )
        return output


class PaginationResponse(NamedTuple):
    """Paginated response parameters."""

    page: int
    per_page: int
    total: int
    total_pages: int

    def as_header(self) -> dict[str, str]:
        """Convert the instance into a dictionary that can be inserted into a HTTP header."""
        return {
            "page": str(self.page),
            "per-page": str(self.per_page),
            "total": str(self.total),
            "total-pages": str(self.total_pages),
        }


_P = ParamSpec("_P")


def paginate(
    f: Callable[Concatenate[Request, _P], Coroutine[Any, Any, tuple[Sequence[Any], int]]],
) -> Callable[Concatenate[Request, _P], Coroutine[Any, Any, JSONResponse]]:
    """Serializes the response to JSON and adds the required pagination headers to the response.

    The handler should return first the list of items and then the total count from the DB.
    """

    @wraps(f)
    async def decorated_function(request: Request, *args: _P.args, **kwargs: _P.kwargs) -> JSONResponse:
        default_page_number = 1
        default_number_of_elements_per_page = 20
        query_args: dict[str, str] = request.get_args() or {}
        page_parameter = cast(int | str, query_args.get("page", default_page_number))
        try:
            page = int(page_parameter)
        except ValueError as err:
            raise errors.ValidationError(message=f"Invalid value for parameter 'page': {page_parameter}") from err
        if page < 1:
            raise errors.ValidationError(message="Parameter 'page' must be a natural number")

        per_page_parameter = cast(int | str, query_args.get("per_page", default_number_of_elements_per_page))
        try:
            per_page = int(per_page_parameter)
        except ValueError as err:
            raise errors.ValidationError(
                message=f"Invalid value for parameter 'per_page': {per_page_parameter}"
            ) from err
        if per_page < 1 or per_page > 100:
            raise errors.ValidationError(message="Parameter 'per_page' must be between 1 and 100")

        pagination_req = PaginationRequest(page, per_page)
        kwargs["pagination"] = pagination_req
        items, db_count = await f(request, *args, **kwargs)
        total_pages = ceil(db_count / per_page)

        pagination = PaginationResponse(page, per_page, db_count, total_pages)
        return json(items, headers=pagination.as_header())

    return decorated_function


_T = TypeVar("_T")


async def paginate_queries(
    req: PaginationRequest, session: AsyncSession, stmts: list[tuple[Select[tuple[_T]], int]]
) -> list[_T]:
    """Paginate several different queries as if they were part of a single table."""
    # NOTE: We ignore the possibility that a count for a statement is not accurate. I.e. the count
    # says that the statement should return 10 items but the statement truly returns 8 or vice-versa.
    # To fully account for edge cases of inaccuracry in the expected number of results
    # we would have to run every query passed in - even though the offset is so high that we would only need
    # to run 1 or 2 queries out of a large list.
    output: list[_T] = []
    max_offset = 0
    stmt_offset = 0
    offset_discount = 0
    for stmt, stmt_cnt in stmts:
        max_offset += stmt_cnt
        if req.offset >= max_offset:
            offset_discount += stmt_cnt
            continue
        stmt_offset = req.offset - offset_discount if req.offset > 0 else 0
        res_scalar = await session.scalars(stmt.offset(stmt_offset).limit(req.per_page))
        res = res_scalar.all()
        num_required = req.per_page - len(output)
        if num_required >= len(res):
            output.extend(res)
        else:
            output.extend(res[:num_required])
            return output
    return output
