from datetime import timedelta

import pytest
import pytest_asyncio
import schemathesis
from hypothesis import HealthCheck, settings
from sanic_testing.testing import SanicASGITestClient
from schemathesis.hooks import HookContext
from schemathesis.specs.openapi.schemas import BaseOpenAPISchema


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
def filter_headers(context: HookContext, headers: dict[str, str]) -> bool:
    op = context.operation
    if op.method.upper() == "PATCH" and op.path == "/projects/{project_id}":
        if_match = headers.get("If-Match")
        if if_match and isinstance(if_match, str):
            try:
                if_match.encode("ascii")
                return True
            except UnicodeEncodeError:
                return False
    return True


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


@pytest.mark.schemathesis
@pytest.mark.asyncio
@schema.parametrize(validate_schema=True)
@settings(max_examples=5, suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.data_too_large])
async def test_api_schemathesis(
    case: schemathesis.Case, sanic_client: SanicASGITestClient, admin_headers: dict
) -> None:
    req_kwargs = case.as_requests_kwargs(headers=admin_headers)
    _, res = await sanic_client.request(**req_kwargs)
    res.request.uri = str(res.url)
    if all(slow[0] != case.path or slow[1] != case.method for slow in ALLOWED_SLOW_ENDPOINTS):
        assert res.elapsed <= timedelta(milliseconds=100), f"{case.path}:{case.method}"
    case.validate_response(res)
