"""Tests for the OpenMeter client, using an in-memory fake of the OpenMeter API."""

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.errors import errors
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.resource_usage.config import OpenMeterConfig
from renku_data_services.resource_usage.core import ResourceUsageService
from renku_data_services.resource_usage.db import ResourceRequestsRepo
from renku_data_services.resource_usage.metering import (
    MeteredEntitlementValue,
    NonMeteredEntitlementValue,
    OpenMeterClient,
)
from renku_data_services.resource_usage.model import (
    Credit,
    CreditBalance,
    CreditUsage,
    ResourceClassCostWithPool,
    next_week_start,
    week_start,
)
from test.components.renku_data_services.resource_usage.test_db import create_resource_class

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
        # Without windowSize, OpenMeter returns one window spanning the whole queried period.
        window = {
            "windowStart": body.get("from", "2026-01-01T00:00:00Z"),
            "windowEnd": body.get("to", "2026-02-01T00:00:00Z"),
        }
        if user_filter is None:
            rows = [
                {
                    "value": sum(v for (s, _), v in METER_USAGE.items() if s == subject),
                    "subject": subject,
                    "groupBy": {},
                    **window,
                }
                for subject in subjects
                if any(s == subject for s, _ in METER_USAGE)
            ]
        else:
            rows = [
                {"value": v, "subject": s, "groupBy": {"user_id": u}, **window}
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
    assert isinstance(result, CreditUsage)
    assert result.value == Credit.zero()


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
    assert datetime.fromisoformat(body["from"]) == PERIOD_FROM
    assert datetime.fromisoformat(body["to"]) == PERIOD_TO


@pytest.mark.parametrize(
    "current_time,expected_start",
    [
        # Monday at midnight is the start of its own week
        (datetime(2026, 11, 16, 0, 0, tzinfo=UTC), datetime(2026, 11, 16, tzinfo=UTC)),
        # Wednesday afternoon: the window starts on Monday at midnight, not at the current time of day
        (datetime(2026, 11, 18, 15, 30, tzinfo=UTC), datetime(2026, 11, 16, tzinfo=UTC)),
        # Sunday just before midnight still belongs to the same week
        (datetime(2026, 11, 22, 23, 59, tzinfo=UTC), datetime(2026, 11, 16, tzinfo=UTC)),
        # Times in other timezones are converted to UTC first: this is Sunday 23:00 UTC
        (datetime.fromisoformat("2026-11-23T01:00:00+02:00"), datetime(2026, 11, 16, tzinfo=UTC)),
    ],
)
async def test_get_usage_of_week(
    client: OpenMeterClient, fake_openmeter: FakeOpenMeter, current_time: datetime, expected_start: datetime
) -> None:
    """The weekly usage is queried from Monday 00:00 UTC up to the current time, including today."""
    result = await client.get_usage_of_week(resource_pool_id=1, user_id=EXISTING_USER_ID, current_time=current_time)
    assert result.value == Credit.from_int(12)
    body = fake_openmeter.meter_query_bodies()[-1]
    assert datetime.fromisoformat(body["from"]) == expected_start
    assert datetime.fromisoformat(body["to"]) == current_time


async def test_query_compute_usage_error(client: OpenMeterClient, fake_openmeter: FakeOpenMeter) -> None:
    """Test that an unexpected status from OpenMeter raises an error."""
    fake_openmeter.fail_with_status = 500
    with pytest.raises(errors.ThirdPartyAPIError):
        await client.get_usage(resource_pool_id=1, user_id=None)


async def test_query_customer_entitlement_value(client: OpenMeterClient) -> None:
    """Test querying a customer entitlement value."""
    result = await client.query_customer_entitlement_value(EXISTING_CUSTOMER_KEY, EXISTING_FEATURE_KEY)
    assert isinstance(result, MeteredEntitlementValue)
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


async def test_get_balance(client: OpenMeterClient) -> None:
    """The balance of a pool is the entitlement balance and it expires at the end of the usage period."""
    result = await client.get_balance(resource_pool_id=1)
    assert result == CreditBalance(Credit.from_int(80), PERIOD_TO)


async def test_get_limit(client: OpenMeterClient) -> None:
    """The limit of a pool for the current period is balance + usage - overage."""
    result = await client.get_limit(resource_pool_id=1)
    assert result == CreditUsage(Credit.from_int(100), start=PERIOD_FROM, end=PERIOD_TO)


async def test_get_limit_with_overage(client: OpenMeterClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Usage that is not covered by grants is not part of the limit."""
    monkeypatch.setitem(
        ENTITLEMENT_VALUES,
        (EXISTING_CUSTOMER_KEY, EXISTING_FEATURE_KEY),
        {"hasAccess": False, "balance": 0.0, "usage": 120.0, "overage": 20.0, "totalAvailableGrantAmount": 100.0},
    )
    result = await client.get_limit(resource_pool_id=1)
    assert result is not None
    assert result.value == Credit.from_int(100)
    assert await client.get_balance(resource_pool_id=1) == CreditBalance(Credit.zero(), PERIOD_TO)


async def test_get_balance_and_limit_no_entitlement(client: OpenMeterClient) -> None:
    """A pool without an entitlement has no balance and no limit."""
    assert await client.get_balance(resource_pool_id=2) is None
    assert await client.get_limit(resource_pool_id=2) is None


@pytest.mark.parametrize("body", [{"hasAccess": True}, {"hasAccess": False, "config": '{"limit": 5}'}])
async def test_non_metered_entitlement_value(
    client: OpenMeterClient, fake_openmeter: FakeOpenMeter, body: dict[str, Any]
) -> None:
    """Boolean and static entitlement values parse as non-metered and give an unlimited pool limit."""
    fake_openmeter.override_response = httpx.Response(200, json=body)
    result = await client.query_customer_entitlement_value(EXISTING_CUSTOMER_KEY, EXISTING_FEATURE_KEY)
    assert isinstance(result, NonMeteredEntitlementValue)
    assert result.hasAccess is body["hasAccess"]
    assert result.config == body.get("config")
    assert await client.get_balance(resource_pool_id=1) is None
    assert await client.get_limit(resource_pool_id=1) is None


async def test_partial_metered_entitlement_value_falls_back_to_non_metered(
    client: OpenMeterClient, fake_openmeter: FakeOpenMeter
) -> None:
    """A value that does not match the metered schema is parsed as non-metered instead of failing."""
    fake_openmeter.override_response = httpx.Response(200, json={"hasAccess": True, "balance": 80.0})
    result = await client.query_customer_entitlement_value(EXISTING_CUSTOMER_KEY, EXISTING_FEATURE_KEY)
    assert isinstance(result, NonMeteredEntitlementValue)


async def test_get_balance_error(client: OpenMeterClient, fake_openmeter: FakeOpenMeter) -> None:
    """Test that an unexpected status from OpenMeter raises an error."""
    fake_openmeter.fail_with_status = 500
    with pytest.raises(errors.ThirdPartyAPIError):
        await client.get_balance(resource_pool_id=1)


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


async def test_empty_entitlement_body(client: OpenMeterClient, fake_openmeter: FakeOpenMeter) -> None:
    """Test that an empty body from the entitlement endpoints is treated as no entitlement."""
    fake_openmeter.override_response = httpx.Response(200, json={})
    assert await client.query_customer_entitlement(EXISTING_CUSTOMER_KEY, EXISTING_FEATURE_KEY) is None
    assert await client.query_customer_entitlement_value(EXISTING_CUSTOMER_KEY, EXISTING_FEATURE_KEY) is None
    assert await client.get_balance(resource_pool_id=1) is None


@pytest.fixture
async def service(app_manager_instance: DependencyManager, client: OpenMeterClient) -> ResourceUsageService:
    run_migrations_for_app("common")
    repo = ResourceRequestsRepo(app_manager_instance.config.db.async_session_maker)
    await create_resource_class(app_manager_instance)
    return ResourceUsageService(repo=repo, metering_client=client)


async def test_service_get_usage_with_limits(service: ResourceUsageService) -> None:
    """Test getting the usage and limits of a resource pool for a timeframe."""
    result = await service.get_usage_with_limits(
        resource_pool_id=1, user_id=EXISTING_USER_ID, start_date=PERIOD_FROM, end_date=PERIOD_TO
    )
    assert result is not None
    assert result.total_usage.value == 20
    assert result.user_usage is not None
    assert result.user_usage.value == 12
    assert result.pool_limits.total_limit == CreditBalance(Credit.from_int(100), PERIOD_TO)
    assert result.pool_limits.user_limit.value.is_unlimited() is True
    assert result.pool_limits.user_limit.expiry == next_week_start()
    assert result.start_date == PERIOD_FROM
    assert result.end_date == PERIOD_TO


async def test_service_get_user_quota(service: ResourceUsageService) -> None:
    """The user quota includes the usage of the current week next to the remaining quota."""
    await service._repo.set_user_limits(1, Credit.from_int(50))
    result = await service.get_user_quota(resource_pool_id=1, user_id=EXISTING_USER_ID)
    assert result is not None
    assert result.weekly_usage == Credit.from_int(12)
    assert result.remaining == CreditBalance(Credit.from_int(38), next_week_start())


async def test_service_get_usage_with_limits_error(
    service: ResourceUsageService, fake_openmeter: FakeOpenMeter
) -> None:
    """Test that OpenMeter failures are raised when querying usage for a timeframe."""
    fake_openmeter.fail_with_exception = httpx.ConnectError("boom")
    with pytest.raises(errors.ThirdPartyAPIError):
        await service.get_usage_with_limits(
            resource_pool_id=1, user_id=EXISTING_USER_ID, start_date=PERIOD_FROM, end_date=PERIOD_TO
        )


async def test_service_get_limits_pool_without_user_limit(service: ResourceUsageService) -> None:
    """An existing pool without a user limit row has an unlimited user limit instead of being missing."""
    limits = await service.get_limits(resource_pool_id=1)
    assert limits is not None
    assert limits.user_limit.value.is_unlimited() is True
    assert await service.get_limits(resource_pool_id=999) is None


@pytest.mark.parametrize(
    "user_limit,has_entitlement,expected_credits,resets",
    [
        # Pool balance (80) is the binding constraint, it resets at the end of the entitlement period
        (None, True, 80, "period"),
        (200, True, 80, "period"),
        # Weekly user limit is the binding constraint: 50 - 12 used this week, resets next Monday
        (50, True, 38, "week"),
        (50, False, 38, "week"),
        # Usage above the weekly limit is clamped to zero
        (10, True, 0, "week"),
        # Zero means no allowance at all
        (0, True, 0, "week"),
        # No limits anywhere: there is no quota to report
        (None, False, None, None),
    ],
    ids=["pool-only", "pool-binding", "user-binding", "user-only", "user-exhausted", "user-zero", "unlimited"],
)
async def test_service_get_remaining_quota(
    service: ResourceUsageService,
    monkeypatch: pytest.MonkeyPatch,
    user_limit: int | None,
    has_entitlement: bool,
    expected_credits: int | None,
    resets: str | None,
) -> None:
    """The remaining quota is the smaller of the pool balance and what is left of the weekly user limit."""
    key = (EXISTING_CUSTOMER_KEY, EXISTING_FEATURE_KEY)
    if not has_entitlement:
        monkeypatch.delitem(ENTITLEMENTS, key)
        monkeypatch.delitem(ENTITLEMENT_VALUES, key)
    if user_limit is not None:
        await service._repo.set_user_limits(1, Credit.from_int(user_limit))

    result = await service.get_remaining_quota(resource_pool_id=1, user_id=EXISTING_USER_ID)

    if expected_credits is None:
        assert result is None
    else:
        expected_expiry = PERIOD_TO if resets == "period" else next_week_start()
        assert result == CreditBalance(Credit.from_int(expected_credits), expected_expiry)


async def test_service_get_remaining_quota_error(service: ResourceUsageService, fake_openmeter: FakeOpenMeter) -> None:
    """OpenMeter failures are raised so that callers can decide how to handle them."""
    fake_openmeter.fail_with_status = 500
    with pytest.raises(errors.ThirdPartyAPIError):
        await service.get_remaining_quota(resource_pool_id=1, user_id=EXISTING_USER_ID)


RESET_AT = datetime(2026, 11, 23, tzinfo=UTC)


@pytest.mark.parametrize(
    "cost,remaining_quota,expected",
    [
        (None, CreditBalance(Credit.from_int(80), RESET_AT), (None, None)),
        (0, CreditBalance(Credit.from_int(80), RESET_AT), (None, None)),
        (10, None, (None, None)),
        (10, CreditBalance(Credit.unlimited(), None), (None, None)),
        (10, CreditBalance(Credit.from_int(80), RESET_AT), (8.0, RESET_AT)),
        (30, CreditBalance(Credit.from_int(80), RESET_AT), (80 / 30, RESET_AT)),
        (10, CreditBalance(Credit.zero(), RESET_AT), (0.0, RESET_AT)),
        (10, CreditBalance(Credit.from_int(80), None), (8.0, None)),
    ],
    ids=["no-cost", "zero-cost", "no-quota", "unlimited", "remaining", "fractional", "exhausted", "never-resets"],
)
def test_calculate_usage_hours(
    cost: int | None,
    remaining_quota: CreditBalance | None,
    expected: tuple[float, datetime | None] | tuple[None, None],
) -> None:
    """Remaining hours are the remaining credits divided by the hourly cost of the class."""
    resource_class_cost = (
        ResourceClassCostWithPool(resource_pool_id=1, resource_class_id=1, cost=Credit.from_int(cost))
        if cost is not None
        else None
    )
    assert ResourceUsageService.calculate_usage_hours(resource_class_cost, remaining_quota) == expected


@pytest.mark.parametrize(
    "left,right,expected",
    [
        (Credit.from_int(10), Credit.from_int(3), Credit.from_int(7)),
        (Credit.from_int(3), Credit.from_int(10), Credit.zero()),
        (Credit.unlimited(), Credit.from_int(10), Credit.unlimited()),
        (Credit.from_int(10), Credit.unlimited(), Credit.zero()),
    ],
)
def test_credit_subtraction(left: Credit, right: Credit, expected: Credit) -> None:
    """Subtracting credits never goes below zero and unlimited stays unlimited."""
    assert left - right == expected


def test_credit_ordering_and_hash() -> None:
    """Unlimited is larger than any finite amount and all unlimited values are interchangeable."""
    assert Credit.from_int(5) < Credit.unlimited()
    assert not Credit.unlimited() < Credit.from_int(5)
    assert Credit.zero() <= Credit.zero()
    assert min(Credit.unlimited(), Credit.from_int(5)) == Credit.from_int(5)
    assert Credit(-1) == Credit(-5)
    assert hash(Credit(-1)) == hash(Credit(-5))
    assert Credit.from_int(10) * 0.5 == Credit.from_int(5)
    assert Credit.unlimited() * 2 == Credit.unlimited()


def test_week_boundaries() -> None:
    """Weeks start on Monday 00:00 UTC."""
    wednesday = datetime(2026, 11, 18, 15, 30, tzinfo=UTC)
    assert week_start(wednesday) == datetime(2026, 11, 16, tzinfo=UTC)
    assert next_week_start(wednesday) == datetime(2026, 11, 23, tzinfo=UTC)
    assert next_week_start(wednesday) - week_start(wednesday) == timedelta(days=7)
