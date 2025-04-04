import math
import urllib.parse
from datetime import timedelta

import httpx
import pytest
import pytest_asyncio
import schemathesis
from hypothesis import HealthCheck, settings
from sanic_testing.testing import SanicASGITestClient
from schemathesis.checks import ALL_CHECKS
from schemathesis.hooks import HookContext
from schemathesis.specs.openapi.schemas import BaseOpenAPISchema


class _RequestsStatistics(list):
    """Subclass of list to avoid polluting schemathesis logs with data points."""

    def __repr__(self):
        return f"RequestsStatistics(len={len(self)})"


@pytest_asyncio.fixture(scope="session")
async def requests_statistics():
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
        try:
            [h.encode("ascii") for h in headers.values()]
        except UnicodeEncodeError:
            return False
    return True


# Schemathesis keeps generating calls where name of a query parameter is just empty but there is a
# value. I.e. like /api/data/user/secrets?kind=&=null, the second query parameter does not have a name
# and this crashes the server when it tries to validate the query.
@schemathesis.hook
def filter_query(context: HookContext, query: dict[str, str] | None) -> bool:
    op = context.operation
    if op is None:
        return True
    if query:
        client = httpx.Client()
        req = client.build_request(op.method, op.full_path, params=query)
        parsed_query = urllib.parse.parse_qs(req.url.query)
        original_keys = set(query.keys())
        parsed_keys = set(k.decode() for k in parsed_query)
        if original_keys != parsed_keys:
            # urlparse would filter data in query and data tested would not match test case
            return False
    return query is None or ("" not in query and "" not in query.values())


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
EXCLUDE_PATH_PREFIXES = ["/sessions", "/notebooks"]


@pytest.mark.schemathesis
@pytest.mark.asyncio
@schema.parametrize(validate_schema=True)
@settings(max_examples=5, suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.data_too_large])
async def test_api_schemathesis(
    case: schemathesis.Case,
    sanic_client_with_solr: SanicASGITestClient,
    admin_headers: dict,
    requests_statistics: list[timedelta],
) -> None:
    for exclude_prefix in EXCLUDE_PATH_PREFIXES:
        if case.path.startswith(exclude_prefix):
            return
    req_kwargs = case.as_requests_kwargs(headers=admin_headers)
    _, res = await sanic_client_with_solr.request(**req_kwargs)
    res.request.uri = str(res.url)

    if all(slow[0] != case.path or slow[1] != case.method for slow in ALLOWED_SLOW_ENDPOINTS):
        requests_statistics.append(res.elapsed)

    checks = ALL_CHECKS
    if req_kwargs.get("method") == "DELETE" and res.status_code == 204:
        # schemathesis does not currently allow accepting status 204 for negative data, so we ignore that check
        checks = tuple(c for c in checks if c.__name__ != "negative_data_rejection")

    case.validate_response(res, checks=checks)
