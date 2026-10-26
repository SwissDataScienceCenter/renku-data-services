"""Tests for the OpenMeter client, using an in-memory fake of the OpenMeter API."""

import json
import re
from datetime import datetime
from typing import Any

import httpx
import pytest

from renku_data_services.errors import errors
from renku_data_services.resource_usage.config import OpenMeterConfig
from renku_data_services.resource_usage.core import ResourceUsageService
from renku_data_services.resource_usage.metering import EntitlementValueQueryResponse, OpenMeterClient
from renku_data_services.resource_usage.model import Credit, ResourceClassCostWithPool

ENDPOINT_URL = "http://openmeter.test"
EXISTING_USER_ID = "test-user"
OTHER_USER_ID = "other-user"
NON_EXISTING_USER_ID = "non-existing-user"
EXISTING_CUSTOMER_KEY = "renku-pool-1"
NON_EXISTING_CUSTOMER_KEY = "non-existing-customer"
EXISTING_FEATURE_KEY = "compute_units"
NON_EXISTING_FEATURE_KEY = "non_existing_feature"

PERIOD_FROM = datetime.fromisoformat("2026-10-01T00:00:00Z")
PERIOD_TO = datetime.fromisoformat("2026-11-01T00:00:00Z")

# Usage per (subject, user_id) for the `compute_units` meter
METER_USAGE: dict[tuple[str, str], float] = {
    ("renku-pool-1", EXISTING_USER_ID): 12.5,
    ("renku-pool-1", OTHER_USER_ID): 7.5,
    ("renku-pool-2", EXISTING_USER_ID): 3.0,
}

ENTITLEMENTS: dict[tuple[str, str], dict[str, Any]] = {
    (EXISTING_CUSTOMER_KEY, EXISTING_FEATURE_KEY): {
        "activeFrom": "2026-01-01T00:00:00Z",
        "currentUsagePeriod": {"from": PERIOD_FROM.isoformat(), "to": PERIOD_TO.isoformat()},
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
        self.fail_with_exception: Exception | None = None
        self.override_response: httpx.Response | None = None

    def meter_query_bodies(self) -> list[dict[str, Any]]:
        """Return the JSON bodies of all meter queries received so far."""
        return [json.loads(r.content) for r in self.requests if r.url.path.endswith("/query")]

    def handler(self, request: httpx.Request) -> httpx.Response:
        """Dispatch a request to the matching fake endpoint."""
        self.requests.append(request)
        if self.fail_with_exception is not None:
            raise self.fail_with_exception
        if self.override_response is not None:
            return self.override_response
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
    config = OpenMeterConfig(
        enabled=True,
        endpoint_url=ENDPOINT_URL,
        token="test-token",
        meter_key=EXISTING_FEATURE_KEY,
        feature_key=EXISTING_FEATURE_KEY,
        customer_key_prefix="renku-pool-",
    )
    client = OpenMeterClient(config)
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(fake_openmeter.handler))
    return client


async def test_query_compute_usage_nonexisting_user(client: OpenMeterClient) -> None:
    """Test querying compute usage for a non-existing user."""
    result = await client.get_usage(resource_pool_id=1, user_id=NON_EXISTING_USER_ID, start_date=None, end_date=None)
    assert isinstance(result, Credit)
    assert result == Credit.zero()


async def test_query_compute_usage_existing_user(client: OpenMeterClient, fake_openmeter: FakeOpenMeter) -> None:
    """Test querying compute usage for an existing user."""
    result = await client.get_usage(resource_pool_id=1, user_id=EXISTING_USER_ID, start_date=None, end_date=None)
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
    result = await client.get_usage(resource_pool_id=1, user_id=None, start_date=None, end_date=None)
    assert result.value == 20
    assert fake_openmeter.meter_query_bodies()[-1] == {"subject": ["renku-pool-1"]}


async def test_query_compute_usage_with_dates(client: OpenMeterClient, fake_openmeter: FakeOpenMeter) -> None:
    """Test that the date range is forwarded to OpenMeter."""
    await client.get_usage(resource_pool_id=1, user_id=None, start_date=PERIOD_FROM, end_date=PERIOD_TO)
    body = fake_openmeter.meter_query_bodies()[-1]
    assert body["from"] == PERIOD_FROM.isoformat()
    assert body["to"] == PERIOD_TO.isoformat()


async def test_query_compute_usage_error(client: OpenMeterClient, fake_openmeter: FakeOpenMeter) -> None:
    """Test that an unexpected status from OpenMeter raises an error."""
    fake_openmeter.fail_with_status = 500
    with pytest.raises(errors.ThirdPartyAPIError):
        await client.get_usage(resource_pool_id=1, user_id=None)


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


async def test_get_resource_pool_total_limit(client: OpenMeterClient) -> None:
    """Test getting the total limit of a resource pool with an entitlement."""
    result = await client.get_resource_pool_total_limit(resource_pool_id=1)
    assert result == Credit.from_int(100)


async def test_get_resource_pool_total_limit_no_entitlement(client: OpenMeterClient) -> None:
    """Test getting the total limit of a resource pool without an entitlement."""
    result = await client.get_resource_pool_total_limit(resource_pool_id=2)
    assert result.is_unlimited() is True


async def test_get_resource_pool_total_limit_error(client: OpenMeterClient, fake_openmeter: FakeOpenMeter) -> None:
    """Test that an unexpected status from OpenMeter raises an error."""
    fake_openmeter.fail_with_status = 500
    with pytest.raises(errors.ThirdPartyAPIError):
        await client.get_resource_pool_total_limit(resource_pool_id=1)


@pytest.mark.parametrize("exception", [httpx.ConnectError("boom"), httpx.ReadTimeout("boom")])
async def test_query_compute_usage_transport_error(
    client: OpenMeterClient, fake_openmeter: FakeOpenMeter, exception: Exception
) -> None:
    """Test that transport errors and timeouts are raised as ThirdPartyAPIError."""
    fake_openmeter.fail_with_exception = exception
    with pytest.raises(errors.ThirdPartyAPIError) as exc_info:
        await client.get_usage(resource_pool_id=1, user_id=None)
    assert exc_info.value.__cause__ is exception


async def test_query_compute_usage_invalid_json(client: OpenMeterClient, fake_openmeter: FakeOpenMeter) -> None:
    """Test that a non-JSON body from OpenMeter raises an error."""
    fake_openmeter.override_response = httpx.Response(200, text="not json")
    with pytest.raises(errors.ThirdPartyAPIError):
        await client.get_usage(resource_pool_id=1, user_id=None)


async def test_query_compute_usage_invalid_response(client: OpenMeterClient, fake_openmeter: FakeOpenMeter) -> None:
    """Test that a meter response that does not match the expected model raises an error."""
    fake_openmeter.override_response = httpx.Response(200, json={"foo": 1})
    with pytest.raises(errors.ThirdPartyAPIError):
        await client.get_usage(resource_pool_id=1, user_id=None)


async def test_get_current_period_invalid_entitlement(client: OpenMeterClient, fake_openmeter: FakeOpenMeter) -> None:
    """Test that an entitlement without a current usage period raises an error."""
    entitlement = dict(ENTITLEMENTS[(EXISTING_CUSTOMER_KEY, EXISTING_FEATURE_KEY)])
    del entitlement["currentUsagePeriod"]
    fake_openmeter.override_response = httpx.Response(200, json=entitlement)
    with pytest.raises(errors.ThirdPartyAPIError):
        await client.get_current_period(resource_pool_id=1)
    assert fake_openmeter.meter_query_bodies() == []


async def test_empty_entitlement_body(client: OpenMeterClient, fake_openmeter: FakeOpenMeter) -> None:
    """Test that an empty body from the entitlement endpoints is treated as no entitlement."""
    fake_openmeter.override_response = httpx.Response(200, json={})
    assert await client.query_customer_entitlement(EXISTING_CUSTOMER_KEY, EXISTING_FEATURE_KEY) is None
    assert await client.query_customer_entitlement_value(EXISTING_CUSTOMER_KEY, EXISTING_FEATURE_KEY) is None
    result = await client.get_resource_pool_total_limit(resource_pool_id=1)
    assert result.is_unlimited() is True


@pytest.fixture
def service(client: OpenMeterClient) -> ResourceUsageService:
    # The repo is not used for querying usage
    return ResourceUsageService(repo=None, metering_client=client)  # type: ignore[arg-type]


async def test_service_get_current_usage_with_limits(service: ResourceUsageService) -> None:
    """Test getting the current usage and limits of a resource pool."""
    result = await service.get_current_usage_with_limits(resource_pool_id=1, user_id=EXISTING_USER_ID)
    assert result is not None
    assert result.total_usage.value == 20
    assert result.user_usage is not None
    assert result.user_usage.value == 12
    assert result.pool_limits.total_limit == Credit.from_int(100)
    assert result.pool_limits.user_limit.is_unlimited() is True
    assert result.start_date == PERIOD_FROM
    assert result.end_date == PERIOD_TO


@pytest.mark.parametrize(
    "failure",
    [{"fail_with_status": 500}, {"fail_with_exception": httpx.ConnectError("boom")}],
    ids=["status", "transport"],
)
async def test_service_get_current_usage_with_limits_error(
    service: ResourceUsageService, fake_openmeter: FakeOpenMeter, failure: dict[str, Any]
) -> None:
    """Test that OpenMeter failures disable the quota check instead of raising."""
    for attr, value in failure.items():
        setattr(fake_openmeter, attr, value)
    assert await service.get_current_usage_with_limits(resource_pool_id=1, user_id=EXISTING_USER_ID) is None


async def test_service_get_usage_with_limits_error(
    service: ResourceUsageService, fake_openmeter: FakeOpenMeter
) -> None:
    """Test that OpenMeter failures are raised when querying usage for a timeframe."""
    fake_openmeter.fail_with_exception = httpx.ConnectError("boom")
    with pytest.raises(errors.ThirdPartyAPIError):
        await service.get_usage_with_limits(
            resource_pool_id=1, user_id=EXISTING_USER_ID, start_date=PERIOD_FROM, end_date=PERIOD_TO
        )


async def test_service_calculate_usage_hours_with_no_cost(service: ResourceUsageService) -> None:
    """Test that calculate_usage_hours returns (None, None) when resource_class_cost is None."""
    usage = await service.get_usage_with_limits(resource_pool_id=1, user_id=EXISTING_USER_ID)
    remaining_quota = service.get_remaining_quota(usage)
    remaining_hours, total_hours = service.calculate_usage_hours(
        resource_class_cost=None,
        usage=usage,
        remaining_quota=remaining_quota,
    )
    assert remaining_hours is None
    assert total_hours is None


async def test_service_calculate_usage_hours_with_zero_cost(service: ResourceUsageService) -> None:
    """Test that calculate_usage_hours returns (None, None) when resource_class_cost.cost.value is 0."""
    usage = await service.get_usage_with_limits(resource_pool_id=1, user_id=EXISTING_USER_ID)
    remaining_quota = service.get_remaining_quota(usage)
    resource_class_cost = ResourceClassCostWithPool(
        resource_pool_id=1,
        resource_class_id=1,
        cost=Credit.from_int(0),
    )
    remaining_hours, total_hours = service.calculate_usage_hours(
        resource_class_cost=resource_class_cost,
        usage=usage,
        remaining_quota=remaining_quota,
    )
    assert remaining_hours is None
    assert total_hours is None


async def test_service_calculate_usage_hours_with_usage(service: ResourceUsageService) -> None:
    """Test that calculate_usage_hours returns correct values when resource_class_cost is valid."""
    usage = await service.get_usage_with_limits(resource_pool_id=1, user_id=EXISTING_USER_ID)
    remaining_quota = service.get_remaining_quota(usage)
    resource_class_cost = ResourceClassCostWithPool(
        resource_pool_id=1,
        resource_class_id=1,
        cost=Credit.from_int(10),
    )
    remaining_hours, total_hours = service.calculate_usage_hours(
        resource_class_cost=resource_class_cost,
        usage=usage,
        remaining_quota=remaining_quota,
    )
    assert remaining_hours == 8.0  # (100 - 20) / 10
    assert total_hours == 10.0  # 100 / 10


async def test_service_calculate_usage_hours_with_negative_remaining_quota(service: ResourceUsageService) -> None:
    """Test that calculate_usage_hours returns 0 remaining hours when remaining_quota is negative."""
    usage = await service.get_usage_with_limits(resource_pool_id=1, user_id=EXISTING_USER_ID)
    remaining_quota = -10.0  # Simulate negative remaining quota
    resource_class_cost = ResourceClassCostWithPool(
        resource_pool_id=1,
        resource_class_id=1,
        cost=Credit.from_int(10),
    )
    remaining_hours, total_hours = service.calculate_usage_hours(
        resource_class_cost=resource_class_cost,
        usage=usage,
        remaining_quota=remaining_quota,
    )
    assert remaining_hours == 0.0
    assert total_hours == 10.0  # 100 / 10


async def test_service_calculate_usage_hours_with_unlimited_total_quota(service: ResourceUsageService) -> None:
    """Test that calculate_usage_hours returns None for total_hours when total quota is unlimited."""
    usage = await service.get_usage_with_limits(resource_pool_id=2, user_id=EXISTING_USER_ID)
    remaining_quota = service.get_remaining_quota(usage)
    resource_class_cost = ResourceClassCostWithPool(
        resource_pool_id=1,
        resource_class_id=1,
        cost=Credit.from_int(10),
    )
    remaining_hours, total_hours = service.calculate_usage_hours(
        resource_class_cost=resource_class_cost,
        usage=usage,
        remaining_quota=remaining_quota,
    )
    assert remaining_hours is None
    assert total_hours is None
