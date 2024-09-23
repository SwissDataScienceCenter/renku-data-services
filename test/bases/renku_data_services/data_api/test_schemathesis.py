import math
from datetime import timedelta

import pytest
import pytest_asyncio
import schemathesis
from hypothesis import HealthCheck, settings
from sanic_testing.testing import SanicASGITestClient
from schemathesis.hooks import HookContext
from schemathesis.specs.openapi.schemas import BaseOpenAPISchema


class _RequestsStatistics(list):
    """Subclass of list to avoid polluting schemathesis logs with data points."""

    def __repr__(self):
        return f"RequestsStatistics(len={len(self)})"


@pytest.fixture(scope="session")
def requests_statistics():
    stats = _RequestsStatistics()
    yield stats

    if len(stats) < 2:
        return

    stats = sorted(stats)
    p95 = stats[math.floor(0.95 * len(stats))]

    assert p95 < timedelta(milliseconds=100), f"The p95 response time {p95} was >= 100 ms"


@pytest_asyncio.fixture
async def apispec(sanic_client: SanicASGITestClient) -> BaseOpenAPISchema:
    _, res = await sanic_client.get("/api/data/spec.json")
    assert res.status_code == 200
    schema = res.json
    # NOTE: If security is not reset then schemathesis generates random values for the Authorization headers
    # and some of these can break the header normalization that httpx library uses to send requests.
    # See https://github.com/schemathesis/schemathesis/issues/1142
    schema["security"] = []
    return schemathesis.from_dict(schema)


# Same issue as for "security" for the "If-Match" header.
# We skip header values which cannot be encoded as ascii.
@schemathesis.hook
def filter_headers(context: HookContext, headers: dict[str, str] | None) -> bool:
    op = context.operation
    if headers is not None and op.method.upper() == "PATCH":
        if_match = headers.get("If-Match")
        if if_match and isinstance(if_match, str):
            try:
                if_match.encode("ascii")
                return True
            except UnicodeEncodeError:
                return False
    return True


# Schemathesis keeps generating calls where name of a query parameter is just empty but there is a
# value. I.e. like /api/data/user/secrets?kind=&=null, the second query parameter does not have a name
# and this crashes the server when it tries to validate the query.
@schemathesis.hook
def filter_query(context: HookContext, query: dict[str, str] | None) -> bool:
    return query is None or "" not in query


schema = schemathesis.from_pytest_fixture(
    "apispec",
    data_generation_methods=schemathesis.DataGenerationMethod.all(),
    sanitize_output=False,
)

ALLOWED_SLOW_ENDPOINTS = [
    ("/user/secrets", "POST"),  # encryption of secrets is a costly operation
    ("/user/secrets/{secret_id}", "PATCH"),
    ("/user/secret_key", "GET"),
    ("/oauth2/providers", "POST"),
]

# TODO: RE-enable schemathesis when CI setup for notebooks / sessions is ready
EXCLUDE_PATH_PREFIXES = [
    "/sessions",
    "/notebooks",
]


@pytest.mark.schemathesis
@pytest.mark.asyncio
@schema.parametrize(validate_schema=True)
@settings(max_examples=5, suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.data_too_large])
async def test_api_schemathesis(
    case: schemathesis.Case,
    sanic_client: SanicASGITestClient,
    admin_headers: dict,
    requests_statistics: list[timedelta],
) -> None:
    for exclude_prefix in EXCLUDE_PATH_PREFIXES:
        if case.path.startswith(exclude_prefix):
            return
    req_kwargs = case.as_requests_kwargs(headers=admin_headers)
    _, res = await sanic_client.request(**req_kwargs)
    res.request.uri = str(res.url)
    if all(slow[0] != case.path or slow[1] != case.method for slow in ALLOWED_SLOW_ENDPOINTS):
        requests_statistics.append(res.elapsed)
    case.validate_response(res)
