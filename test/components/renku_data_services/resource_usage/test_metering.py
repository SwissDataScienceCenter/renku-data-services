"""Tests for the OpenMeter client, using an in-memory fake of the OpenMeter API."""

import json
import re
from typing import Any

import httpx
import pytest

from renku_data_services.errors import errors
from renku_data_services.resource_usage.metering import EntitlementValueQueryResponse, OpenMeterClient
from renku_data_services.resource_usage.model import Credit

ENDPOINT_URL = "http://openmeter.test"
EXISTING_USER_ID = "test-user"
OTHER_USER_ID = "other-user"
NON_EXISTING_USER_ID = "non-existing-user"
EXISTING_CUSTOMER_KEY = "renku-pool-1"
NON_EXISTING_CUSTOMER_KEY = "non-existing-customer"
EXISTING_FEATURE_KEY = "compute_units"
NON_EXISTING_FEATURE_KEY = "non_existing_feature"

PERIOD_FROM = "2026-10-01T00:00:00Z"
PERIOD_TO = "2026-11-01T00:00:00Z"

# Usage per (subject, user_id) for the `compute_units` meter
METER_USAGE: dict[tuple[str, str], float] = {
    ("renku-pool-1", EXISTING_USER_ID): 12.5,
    ("renku-pool-1", OTHER_USER_ID): 7.5,
    ("renku-pool-2", EXISTING_USER_ID): 3.0,
}

ENTITLEMENTS: dict[tuple[str, str], dict[str, Any]] = {
    (EXISTING_CUSTOMER_KEY, EXISTING_FEATURE_KEY): {
        "activeFrom": "2026-01-01T00:00:00Z",
        "currentUsagePeriod": {"from": PERIOD_FROM, "to": PERIOD_TO},
        "customerId": "01J0000000000000000000000",
        "customerKey": EXISTING_CUSTOMER_KEY,
        "featureId": "01J0000000000000000000001",
        "featureKey": EXISTING_FEATURE_KEY,
        "isSoftLimit": False,
        "measureUsageFrom": "2026-01-01T00:00:00Z",
        "type": "metered",
        "usagePeriod": {"interval": "MONTH", "anchor": "2026-01-01T00:00:00Z"},
    }
}

ENTITLEMENT_VALUES: dict[tuple[str, str], dict[str, Any]] = {
    (EXISTING_CUSTOMER_KEY, EXISTING_FEATURE_KEY): {
        "hasAccess": True,
        "balance": 80.0,
        "usage": 20.0,
        "overage": 0.0,
        "totalAvailableGrantAmount": 100.0,
    }
}


class FakeOpenMeter:
    """Minimal in-memory implementation of the OpenMeter endpoints used by the client."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.fail_with_status: int | None = None

    def meter_query_bodies(self) -> list[dict[str, Any]]:
        """Return the JSON bodies of all meter queries received so far."""
        return [json.loads(r.content) for r in self.requests if r.url.path.endswith("/query")]

    def handler(self, request: httpx.Request) -> httpx.Response:
        """Dispatch a request to the matching fake endpoint."""
        self.requests.append(request)
        if self.fail_with_status is not None:
            return httpx.Response(self.fail_with_status, text="fake failure")

        path = request.url.path
        if m := re.fullmatch(r"/api/v1/meters/([^/]+)/query", path):
            return self._query_meter(m.group(1), json.loads(request.content))
        if m := re.fullmatch(r"/api/v2/customers/([^/]+)/entitlements/([^/]+)/value", path):
            value = ENTITLEMENT_VALUES.get((m.group(1), m.group(2)))
            return httpx.Response(200, json=value) if value is not None else httpx.Response(404)
        if m := re.fullmatch(r"/api/v2/customers/([^/]+)/entitlements/([^/]+)", path):
            entitlement = ENTITLEMENTS.get((m.group(1), m.group(2)))
            return httpx.Response(200, json=entitlement) if entitlement is not None else httpx.Response(404)
        return httpx.Response(404)

    def _query_meter(self, meter_key: str, body: dict[str, Any]) -> httpx.Response:
        if meter_key != EXISTING_FEATURE_KEY:
            return httpx.Response(404)
        subjects = body["subject"]
        user_filter = body.get("advancedMeterGroupByFilters", {}).get("user_id", {}).get("$eq")
        if user_filter is None:
            rows = [
                {"value": sum(v for (s, _), v in METER_USAGE.items() if s == subject), "subject": subject}
                for subject in subjects
                if any(s == subject for s, _ in METER_USAGE)
            ]
        else:
            rows = [
                {"value": v, "subject": s, "groupBy": {"user_id": u}}
                for (s, u), v in METER_USAGE.items()
                if s in subjects and u == user_filter
            ]
        return httpx.Response(200, json={"data": rows})


@pytest.fixture
def fake_openmeter() -> FakeOpenMeter:
    return FakeOpenMeter()


@pytest.fixture
def client(fake_openmeter: FakeOpenMeter) -> OpenMeterClient:
    client = OpenMeterClient(endpoint_url=ENDPOINT_URL, token="test-token")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(fake_openmeter.handler))
    return client


async def test_query_compute_usage_nonexisting_user(client: OpenMeterClient) -> None:
    """Test querying compute usage for a non-existing user."""
    result = await client.query_compute_usage(
        resource_pool_id=1, user_id=NON_EXISTING_USER_ID, start_date=None, end_date=None
    )
    assert isinstance(result, Credit)
    assert result == Credit.zero()


async def test_query_compute_usage_existing_user(client: OpenMeterClient, fake_openmeter: FakeOpenMeter) -> None:
    """Test querying compute usage for an existing user."""
    result = await client.query_compute_usage(
        resource_pool_id=1, user_id=EXISTING_USER_ID, start_date=None, end_date=None
    )
    assert result.value == 12

    request = fake_openmeter.requests[-1]
    assert request.headers["Authorization"] == "Bearer test-token"
    assert fake_openmeter.meter_query_bodies()[-1] == {
        "subject": ["renku-pool-1"],
        "advancedMeterGroupByFilters": {"user_id": {"$eq": EXISTING_USER_ID}},
        "groupBy": ["user_id"],
    }


async def test_query_compute_usage_no_user(client: OpenMeterClient, fake_openmeter: FakeOpenMeter) -> None:
    """Test querying compute usage without specifying a user."""
    result = await client.query_compute_usage(resource_pool_id=1, user_id=None, start_date=None, end_date=None)
    assert result.value == 20
    assert fake_openmeter.meter_query_bodies()[-1] == {"subject": ["renku-pool-1"]}


async def test_query_compute_usage_with_dates(client: OpenMeterClient, fake_openmeter: FakeOpenMeter) -> None:
    """Test that the date range is forwarded to OpenMeter."""
    await client.query_compute_usage(resource_pool_id=1, user_id=None, start_date=PERIOD_FROM, end_date=PERIOD_TO)
    body = fake_openmeter.meter_query_bodies()[-1]
    assert body["from"] == PERIOD_FROM
    assert body["to"] == PERIOD_TO


async def test_query_compute_usage_error(client: OpenMeterClient, fake_openmeter: FakeOpenMeter) -> None:
    """Test that an unexpected status from OpenMeter raises an error."""
    fake_openmeter.fail_with_status = 500
    with pytest.raises(errors.ThirdPartyAPIError):
        await client.query_compute_usage(resource_pool_id=1, user_id=None)


async def test_query_customer_entitlement_value(client: OpenMeterClient) -> None:
    """Test querying a customer entitlement value."""
    result = await client.query_customer_entitlement_value(EXISTING_CUSTOMER_KEY, EXISTING_FEATURE_KEY)
    assert isinstance(result, EntitlementValueQueryResponse)
    assert result.hasAccess is True
    assert result.balance == 80.0
    assert result.usage == 20.0
    assert result.overage == 0.0
    assert result.totalAvailableGrantAmount == 100.0


async def test_query_customer_entitlement_value_nonexisting_feature(client: OpenMeterClient) -> None:
    """Test querying an entitlement value for a non-existing feature."""
    result = await client.query_customer_entitlement_value(EXISTING_CUSTOMER_KEY, NON_EXISTING_FEATURE_KEY)
    assert result is None


async def test_query_customer_entitlement_value_nonexisting_customer(client: OpenMeterClient) -> None:
    """Test querying an entitlement value for a non-existing customer."""
    result = await client.query_customer_entitlement_value(NON_EXISTING_CUSTOMER_KEY, EXISTING_FEATURE_KEY)
    assert result is None


async def test_query_customer_entitlement_value_error(client: OpenMeterClient, fake_openmeter: FakeOpenMeter) -> None:
    """Test that an unexpected status from OpenMeter raises an error."""
    fake_openmeter.fail_with_status = 500
    with pytest.raises(errors.ThirdPartyAPIError):
        await client.query_customer_entitlement_value(EXISTING_CUSTOMER_KEY, EXISTING_FEATURE_KEY)


async def test_query_compute_usage_with_limits_no_entitlement(
    client: OpenMeterClient, fake_openmeter: FakeOpenMeter
) -> None:
    """Test querying compute usage with limits when no entitlement is found."""
    result = await client.query_compute_usage_with_limits(
        resource_pool_id=2, user_id=EXISTING_USER_ID, feature_key=EXISTING_FEATURE_KEY
    )
    assert result.user_usage.value == 3
    assert result.total_usage.value == 3
    assert result.pool_limits.total_limit.value == 0
    assert result.pool_limits.user_limit.value == 0
    # Usage is computed over the entire history
    assert all("from" not in body and "to" not in body for body in fake_openmeter.meter_query_bodies())


async def test_query_compute_usage_with_limits_existing_entitlement(
    client: OpenMeterClient, fake_openmeter: FakeOpenMeter
) -> None:
    """Test querying compute usage with limits when an entitlement is found."""
    result = await client.query_compute_usage_with_limits(
        resource_pool_id=1, user_id=EXISTING_USER_ID, feature_key=EXISTING_FEATURE_KEY
    )
    assert result.user_usage.value == 12
    assert result.total_usage.value == 20
    assert result.pool_limits.total_limit.value == 100
    assert result.pool_limits.user_limit.value == 0
    # Usage is restricted to the current usage period of the entitlement
    body = fake_openmeter.meter_query_bodies()[-1]
    assert body["from"] == PERIOD_FROM
    assert body["to"] == PERIOD_TO
