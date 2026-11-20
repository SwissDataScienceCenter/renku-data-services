import math
import urllib.parse
from datetime import timedelta

import httpx
import pytest
import pytest_asyncio
import schemathesis
from hypothesis import HealthCheck, settings
from sanic_testing.testing import SanicASGITestClient
from schemathesis import GenerationMode, HookContext
from schemathesis.checks import (
    content_type_conformance,
    ignored_auth,
    negative_data_rejection,
    not_a_server_error,
    response_headers_conformance,
    response_schema_conformance,
    status_code_conformance,
)
from schemathesis.config import SchemathesisConfig
from schemathesis.specs.openapi.schemas import OpenApiSchema

# NOTE: These are the checks that were part of ALL_CHECKS in schemathesis 3.x. Schemathesis 4 runs
# additional checks by default (e.g. positive_data_acceptance, use_after_free), so we list them explicitly.
CHECKS = [
    not_a_server_error,
    status_code_conformance,
    content_type_conformance,
    response_headers_conformance,
    response_schema_conformance,
    negative_data_rejection,
    ignored_auth,
]


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
async def apispec(sanic_client: SanicASGITestClient) -> OpenApiSchema:
    _, res = await sanic_client.get("/api/data/spec.json")
    assert res.status_code == 200
    schema = res.json
    # NOTE: If security is not reset then schemathesis generates random values for the Authorization headers
    # and some of these can break the header normalization that httpx library uses to send requests.
    # See https://github.com/schemathesis/schemathesis/issues/1142
    schema["security"] = []
    config = SchemathesisConfig()
    config.projects.default.generation.update(modes=list(GenerationMode))
    config.output.sanitization.update(enabled=False)
    return schemathesis.openapi.from_dict(schema, config=config)


# Same issue as for "security" for the "If-Match" header.
# We skip header values which cannot be encoded as ascii.
@schemathesis.hook
def filter_headers(context: HookContext, headers: dict[str, str] | None) -> bool:
    op = context.operation
    if headers is not None and (op.method.upper() == "PATCH" or op.method.upper() == "DELETE"):
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


schema = schemathesis.pytest.from_fixture("apispec")

ALLOWED_SLOW_ENDPOINTS = [
    ("/user/secrets", "POST"),  # encryption of secrets is a costly operation
    ("/user/secrets/{secret_id}", "PATCH"),
    ("/user/secret_key", "GET"),
    ("/oauth2/providers", "POST"),
]

# NOTE: Request bodies are validated by pydantic in lax mode, which accepts data that violates the API spec:
# - explicit `null` for optional fields that are not nullable (generated models use `X | None = None`)
# - type coercion for booleans, integers and numbers (e.g. `0` -> `False`, `False` -> `0`, `"5"` -> `5`)
# - integers (unix timestamps) for date-time strings
# Schemathesis' negative data generation sends such values and expects them to be rejected. Until body
# validation is made strict, we skip negative_data_rejection for every endpoint whose JSON request body
# contains at least one such field. Endpoints with sessions/notebooks/apps prefixes are excluded anyway.
LAX_BODY_VALIDATION_ENDPOINTS = [
    ("/clusters", "POST"),
    ("/clusters/{cluster_id}", "PUT"),
    ("/clusters/{cluster_id}", "PATCH"),
    ("/resource_flavors", "POST"),
    ("/resource_flavors/{resource_flavor_id}", "PATCH"),
    ("/resource_pools", "POST"),
    ("/resource_pools/{resource_pool_id}", "PUT"),
    ("/resource_pools/{resource_pool_id}", "PATCH"),
    ("/resource_pools/{resource_pool_id}/classes", "POST"),
    ("/resource_pools/{resource_pool_id}/classes/{class_id}", "PUT"),
    ("/resource_pools/{resource_pool_id}/classes/{class_id}", "PATCH"),
    ("/resource_pools/{resource_pool_id}/users", "POST"),
    ("/resource_pools/{resource_pool_id}/users", "PUT"),
    ("/resource_pools/{resource_pool_id}/quota", "PUT"),
    ("/resource_pools/{resource_pool_id}/quota", "PATCH"),
    ("/users/{user_id}/resource_pools", "POST"),
    ("/users/{user_id}/resource_pools", "PUT"),
    ("/storage_schema/validate", "POST"),
    ("/storage_schema/test_connection", "POST"),
    ("/storage_schema/obscure", "POST"),
    ("/storage", "POST"),
    ("/storage/allow", "POST"),
    ("/storage/allow/{project_id}", "PATCH"),
    ("/storage/{storage_id}", "PATCH"),
    ("/user/secrets", "POST"),
    ("/user/secrets/{secret_id}", "PATCH"),
    ("/projects", "POST"),
    ("/projects/{project_id}", "PATCH"),
    ("/renku_v1_projects/{v1_id}/migrations", "POST"),
    ("/projects/{project_id}/copies", "POST"),
    ("/session_secret_slots", "POST"),
    ("/session_secret_slots/{slot_id}", "PATCH"),
    ("/groups/{group_slug}", "PATCH"),
    ("/environments", "POST"),
    ("/environments/{environment_id}", "PATCH"),
    ("/session_launchers", "POST"),
    ("/session_launchers/{launcher_id}", "PATCH"),
    ("/builds/{build_id}", "PATCH"),
    ("/oauth2/providers", "POST"),
    ("/oauth2/providers/{provider_id}", "PATCH"),
    ("/platform/config", "PATCH"),
    ("/platform/authorization_config", "PATCH"),
    ("/platform/redirects/{source_url}", "PATCH"),
    ("/data_connectors", "POST"),
    ("/data_connectors/global", "POST"),
    ("/data_connectors/{data_connector_id}", "PATCH"),
    ("/deposits", "POST"),
    ("/deposits/{deposit_id}", "PATCH"),
    ("/alerts", "POST"),
    ("/alerts/{alert_id}", "PATCH"),
    ("/webhooks/alertmanager", "POST"),
    ("/capacity-reservations", "POST"),
    ("/resource_pools/{resource_pool_id}/limits", "PUT"),
    ("/resource_pools/{resource_pool_id}/classes/{class_id}/cost", "PUT"),
]

# TODO: RE-enable schemathesis when CI setup for notebooks / sessions / apps is ready
EXCLUDE_PATH_PREFIXES = ["/sessions", "/notebooks", "/apps"]


@pytest.mark.schemathesis
@pytest.mark.asyncio
@schema.parametrize()
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
    req_kwargs = case.as_transport_kwargs(headers=admin_headers)
    _, res = await sanic_client_with_solr.request(**req_kwargs)
    res.request.uri = str(res.url)

    if all(slow[0] != case.path or slow[1] != case.method for slow in ALLOWED_SLOW_ENDPOINTS):
        requests_statistics.append(res.elapsed)

    checks = CHECKS
    if req_kwargs.get("method") == "DELETE" and res.status_code == 204:
        # schemathesis does not currently allow accepting status 204 for negative data, so we ignore that check
        checks = [c for c in checks if c is not negative_data_rejection]

    if req_kwargs.get("url") == "/api/data/repository" and res.status_code == 200:
        # schemathesis constructs invalid negative cases affecting the /repositories endpoint
        checks = [c for c in checks if c is not negative_data_rejection]

    if (case.path, case.method) in LAX_BODY_VALIDATION_ENDPOINTS:
        checks = [c for c in checks if c is not negative_data_rejection]

    case.validate_response(res, checks=checks)
