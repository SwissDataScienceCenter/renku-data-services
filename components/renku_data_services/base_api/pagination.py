"""Classes and decorators used for paginating long responses."""

from functools import wraps
from math import ceil
from typing import Any, Awaitable, Callable, Concatenate, Dict, NamedTuple, Sequence, Tuple, cast

from sanic import Request, json

from renku_data_services import errors


class PaginationRequest(NamedTuple):
    """Request for a paginated response."""

    page: int
    per_page: int

    def __post_init__(self):
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

    def as_header(self) -> Dict[str, str]:
        """Convert the instance into a dictionary that can be inserted into a HTTP header."""
        return {
            "page": str(self.page),
            "per-page": str(self.per_page),
            "total": str(self.total),
            "total-pages": str(self.total_pages),
        }


def paginate(f: Callable[Concatenate[Request, ...], Awaitable[Tuple[Sequence[Any], int]]]):
    """Serializes the response to JSON and adds the required pagination headers to the response.

    The handler should return first the list of items and then the total count from the DB.
    """

    @wraps(f)
    async def decorated_function(request: Request, *args, **kwargs):
        default_page_number = 1
        default_number_of_elements_per_page = 20
        query_args: Dict[str, str] = request.get_args() or {}
        page_parameter = cast(int | str, query_args.get("page", default_page_number))
        try:
            page = int(page_parameter)
        except ValueError:
            raise errors.ValidationError(message=f"Invalid value for parameter 'page': {page_parameter}")
        if page < 1:
            raise errors.ValidationError(message="Parameter 'page' must be a natural number")

        per_page_parameter = cast(int | str, query_args.get("per_page", default_number_of_elements_per_page))
        try:
            per_page = int(per_page_parameter)
        except ValueError:
            raise errors.ValidationError(message=f"Invalid value for parameter 'per_page': {per_page_parameter}")
        if per_page < 1 or per_page > 100:
            raise errors.ValidationError(message="Parameter 'per_page' must be between 1 and 100")

        pagination_req = PaginationRequest(page, per_page)
        items, db_count = await f(request, *args, **kwargs, pagination=pagination_req)
        total_pages = ceil(db_count/per_page)

        pagination = PaginationResponse(page, per_page, db_count, total_pages)
        return json(items, headers=pagination.as_header())

    return decorated_function
