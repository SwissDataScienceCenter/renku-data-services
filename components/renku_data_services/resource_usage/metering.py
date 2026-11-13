"""OpenMeter event emission for session resource usage metering.

API schemas taken from https://openmeter.io/docs/api/open-source.
"""

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, TypeAdapter, ValidationError

from renku_data_services.app_config import logging
from renku_data_services.errors import errors
from renku_data_services.resource_usage.config import OpenMeterConfig
from renku_data_services.resource_usage.model import Credit

logger = logging.getLogger(__file__)


class ResourceUsageMetering(Protocol):
    """Interface for resource usage metering."""

    async def get_usage(
        self,
        resource_pool_id: int,
        user_id: str | None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> Credit:
        """Get compute usage for a resource pool or a specific user from the metering service."""
        ...

    async def get_current_period(self, resource_pool_id: int) -> tuple[datetime | None, datetime | None]:
        """Get the start and end dates of the current usage period defined in the metering service."""
        ...

    async def get_resource_pool_total_limit(self, resource_pool_id: int) -> Credit:
        """Get the total usage limit for a resource pool from the metering service."""
        ...


class WindowSize(StrEnum):
    """Query aggrgegation window size."""

    MINUTE = "MINUTE"
    HOUR = "HOUR"
    DAY = "DAY"
    MONTH = "MONTH"


class MeterQueryRow(BaseModel):
    """A row in the result of a meter query."""

    subject: str | None
    """The subject the value is aggregated over. If not specified, the value is aggregated over all subjects."""
    groupBy: dict[str, str | None]
    """The group by values the value is aggregated over."""
    value: float
    """The aggregated value."""
    windowStart: datetime
    """The start of the window the value is aggregated over"""
    windowEnd: datetime
    """The end of the window the value is aggregated over"""
    customerId: str | None = None
    """The customer ID the value is aggregated over."""


class MeterQueryResponse(BaseModel):
    """Response from OpenMeter meter query."""

    data: list[MeterQueryRow]
    from_: datetime | None = Field(alias="from", default=None)
    """The start of the period the usage is queried from.
    If not specified, the usage is queried from the beginning of time."""
    to: datetime | None = None
    """The end of the period the usage is queried to.
    If not specified, the usage is queried up to the current time."""
    windowSize: WindowSize | None = None
    """The window size that the usage is aggregated.
    If not specified, the usage is aggregated over the entire period."""


class MeterQueryRequest(BaseModel):
    """The request body for a meter query."""

    model_config = ConfigDict(populate_by_name=True)

    advancedMeterGroupByFilters: dict[str, Any] | None = None
    """Optional advanced meter group by filters. You can use this to filter for values of the meter groupBy fields."""
    clientId: str | None = None
    """Client ID Useful to track progress of a query."""
    filterCustomerId: list[str] | None = None
    """Filtering by multiple customers."""
    filterGroupBy: dict[str, list[str]] | None = None
    """Simple filter for group bys with exact match."""
    from_: datetime | None = Field(alias="from", default=None)
    """Start date-time in RFC 3339 format. Inclusive."""
    to: datetime | None = None
    """End date-time in RFC 3339 format. Inclusive."""
    groupBy: list[str] | None = None
    """If not specified a single aggregate will be returned for each subject and time window.
    "subject" is a reserved group by value."""
    subject: list[str] | None = None
    """Filtering by multiple subjects."""
    windowSize: WindowSize | None = None
    """If not specified, a single usage aggregate will be returned
    for the entirety of the specified period for each subject and group."""
    windowTimeZone: str | None = None
    """The value is the name of the time zone as defined in the
    IANA Time Zone Database (http://www.iana.org/time-zones).
    If not specified, the UTC timezone will be used."""


class CurrentUsagePeriod(BaseModel):
    """Usage period for OpenMeter entitlement."""

    from_: datetime = Field(alias="from")
    to: datetime


class EntitlementInterval(StrEnum):
    """Human readable period for OpenMeter entitlements."""

    DAY = "DAY"
    WEEK = "WEEK"
    MONTH = "MONTH"
    YEAR = "YEAR"


class UsagePeriod(BaseModel):
    """The period for the entitlement."""

    model_config = ConfigDict(extra="ignore")

    anchor: datetime
    """Indicates the date and time of the period when it rolls over.
    For example, interval: MONTH with anchor: 2026-01-15T00:00:00Z
    resets usage on the 15th of every month at 00:00 UTC."""
    interval: EntitlementInterval | timedelta
    """Note that the timedelta values do not round trip deserialize/serialize.
    Eg: 'P3M' -> timedelta(days=90) -> 'P90D'."""


class MeteredEntitlement(BaseModel):
    """Metered variant of the OpenMeter entitlement query response."""

    activeFrom: datetime
    """The cadence start of the resource."""
    currentUsagePeriod: CurrentUsagePeriod
    customerId: str
    """The identifier unique to the customer."""
    customerKey: str
    """The identifier key unique to the customer."""
    featureId: str
    """The feature the subject is entitled to use."""
    featureKey: str
    """The feature the subject is entitled to use."""
    isSoftLimit: bool
    """If softLimit=true the subject can use the feature even if the entitlement is exhausted,
    hasAccess will always be true."""
    measureUsageFrom: datetime
    """The time from which usage is measured. If not specified on creation, defaults to entitlement creation time."""
    type: Literal["metered"]
    """The type of entitlement."""
    usagePeriod: UsagePeriod
    """The usage period of the entitlement."""


def _entitlement_type(v: Any) -> str:
    """Route metered entitlements to the model and everything else (static, boolean) to a plain dict."""
    entitlement_type = v.get("type") if isinstance(v, dict) else getattr(v, "type", None)
    return "metered" if entitlement_type == "metered" else "other"


EntitlementQueryResponse = Annotated[
    Annotated[MeteredEntitlement, Tag("metered")] | Annotated[dict[str, Any], Tag("other")],
    Discriminator(_entitlement_type),
]
"""Response from OpenMeter entitlement query (EntitlementV2).

Only the metered variant is modelled; static and boolean entitlements are returned as raw dicts.
"""

_entitlement_query_response_adapter: TypeAdapter[EntitlementQueryResponse] = TypeAdapter(EntitlementQueryResponse)


class MeteredEntitlementValue(BaseModel):
    """Value of a metered OpenMeter entitlement."""

    hasAccess: bool
    """Whether the subject has access to the feature. Shared accross all entitlement types."""
    balance: float
    """Metered entitlements are built around a balance calculation where feature usage is deducted
    from the issued grants. Balance represents the remaining balance of the entitlement,
    it's value never turns negative."""
    usage: float
    """The total feature usage in the current period."""
    overage: float
    """Overage represents the usage that wasn't covered by grants,
    e.g. if the subject had a total feature usage of 100 in the period but they were only granted 80,
    there would be 20 overage."""
    totalAvailableGrantAmount: float
    """The summed amount of all grant active at query time PLUS the used amount of since inactive grants."""
    grantBalances: dict[str, float] | None = None
    """The closing balance of each active grant at query time.
    The key is the grant ID and the value is the remaining balance."""


class NonMeteredEntitlementValue(BaseModel):
    """Value of a boolean or static OpenMeter entitlement."""

    hasAccess: bool
    """Whether the subject has access to the feature. Shared accross all entitlement types."""
    config: str | None = None
    """Only available for static entitlements. The JSON parsable config of the entitlement."""


EntitlementValueQueryResponse = Annotated[
    MeteredEntitlementValue | NonMeteredEntitlementValue, Field(union_mode="left_to_right")
]
"""Response from OpenMeter entitlement value query (EntitlementValueV2).

The response has no type field. It is parsed as metered if it has all the metered fields,
otherwise as non-metered (boolean, static, or anything else carrying only hasAccess).
"""

_entitlement_value_query_response_adapter: TypeAdapter[EntitlementValueQueryResponse] = TypeAdapter(
    EntitlementValueQueryResponse
)


def _validate[T: BaseModel](model: type[T], body: Any) -> T:
    try:
        return model.model_validate(body)
    except ValidationError as ex:
        raise errors.ThirdPartyAPIError(message=f"Unexpected OpenMeter response for {model.__name__}.") from ex


class OpenMeterClient:
    """Client for interacting with the OpenMeter API.

    NOTE: This client assumes that all resource pools are represented as OpenMeter customers,
    with the customer having only one subject, which is the resource pool itself.
    The customer key is derived from the resource pool ID using the `_customer_key_prefix` configuration.
    """

    def __init__(self, config: OpenMeterConfig) -> None:
        self._endpoint_url = config.endpoint_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {config.token}"} if config.token else {}
        self._client = httpx.AsyncClient(timeout=30)
        self._meter_key = config.meter_key
        self._feature_key = config.feature_key
        self._customer_key_prefix = config.customer_key_prefix

    async def _request(self, method: str, path: str, *, allow_404: bool = False, **kwargs: Any) -> Any | None:
        """Call OpenMeter and return the decoded JSON body.

        Every failure (transport, timeout, bad status, bad JSON) is raised as ThirdPartyAPIError.
        """
        try:
            resp = await self._client.request(method, f"{self._endpoint_url}{path}", headers=self._headers, **kwargs)
        except httpx.HTTPError as ex:
            logger.warning(f"OpenMeter request {method} {path} failed: {ex}")
            raise errors.ThirdPartyAPIError(message=f"Could not reach OpenMeter: {type(ex).__name__}") from ex
        if allow_404 and resp.status_code == 404:
            return None
        if resp.status_code >= 300 or resp.status_code < 200:
            logger.warning(f"OpenMeter endpoint returned unexpected status {resp.status_code}: {resp.text[:200]}")
            raise errors.ThirdPartyAPIError(
                message=f"Received unexpected status code {resp.status_code} from OpenMeter.",
                detail=f"Message from OpenMeter: {resp.text[:200]}",
            )
        try:
            return resp.json()
        except ValueError as ex:
            logger.warning("OpenMeter returned an invalid JSON body")
            raise errors.ThirdPartyAPIError(message="OpenMeter returned an invalid JSON body.") from ex

    async def query_meter(self, meter_id_or_slug: str, body: dict[str, Any]) -> MeterQueryResponse:
        """Query a meter in OpenMeter."""
        res = await self._request("POST", f"/api/v1/meters/{meter_id_or_slug}/query", json=body)
        return _validate(MeterQueryResponse, res)

    async def query_customer_entitlement(
        self, customer_id_or_key: str, feature_key: str
    ) -> EntitlementQueryResponse | None:
        """Query a customer entitlement in OpenMeter."""
        res = await self._request(
            "GET",
            f"/api/v2/customers/{customer_id_or_key}/entitlements/{feature_key}",
            allow_404=True,
        )
        if not res:
            logger.warning(
                f"No customer entitlement found for customer={customer_id_or_key}, feature_key={feature_key}"
            )
            return None
        try:
            return _entitlement_query_response_adapter.validate_python(res)
        except ValidationError as ex:
            raise errors.ThirdPartyAPIError(
                message="Unexpected OpenMeter response for EntitlementQueryResponse."
            ) from ex

    async def query_customer_entitlement_value(
        self, customer_id_or_key: str, feature_key: str
    ) -> EntitlementValueQueryResponse | None:
        """Query a customer entitlement value in OpenMeter."""
        res = await self._request(
            "GET",
            f"/api/v2/customers/{customer_id_or_key}/entitlements/{feature_key}/value",
            allow_404=True,
        )
        if not res:
            logger.warning(
                f"No customer entitlement value found for customer={customer_id_or_key}, feature_key={feature_key}"
            )
            return None
        try:
            return _entitlement_value_query_response_adapter.validate_python(res)
        except ValidationError as ex:
            raise errors.ThirdPartyAPIError(
                message="Unexpected OpenMeter response for EntitlementValueQueryResponse."
            ) from ex

    def get_resource_pool_key(self, resource_pool_id: int) -> str:
        """Get the OpenMeter customer / subject key for a resource pool."""
        return f"{self._customer_key_prefix}{resource_pool_id}"

    async def get_resource_pool_total_limit(self, resource_pool_id: int) -> Credit:
        """Get the total usage limit for a resource pool from OpenMeter."""
        customer_key = self.get_resource_pool_key(resource_pool_id)
        entitlement_value = await self.query_customer_entitlement_value(customer_key, self._feature_key)
        if entitlement_value is None:
            return Credit.unlimited()
        if not isinstance(entitlement_value, MeteredEntitlementValue):
            logger.warning(
                f"Entitlement for customer={customer_key}, feature_key={self._feature_key} is not metered, "
                "treating the resource pool limit as unlimited"
            )
            return Credit.unlimited()
        return Credit.from_float(entitlement_value.totalAvailableGrantAmount)

    async def get_usage(
        self,
        resource_pool_id: int,
        user_id: str | None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> Credit:
        """Get compute usage for a resource pool or a specific user from OpenMeter.

        If user_id is None, the total usage for the resource pool is returned.
        Otherwise, the usage for the specified user within the resource pool is returned.
        """
        subject_key = self.get_resource_pool_key(resource_pool_id)
        body: dict[str, Any] = {"subject": [subject_key]}
        if start_date is not None:
            body["from"] = start_date.isoformat()
        if end_date is not None:
            body["to"] = end_date.isoformat()
        if user_id is not None:
            user_body = {"advancedMeterGroupByFilters": {"user_id": {"$eq": user_id}}, "groupBy": ["user_id"]}
            body.update(user_body)
        res = await self.query_meter(self._meter_key, body)
        return Credit.from_float(res.data[0].value) if res.data else Credit.zero()

    async def get_current_period(self, resource_pool_id: int) -> tuple[datetime | None, datetime | None]:
        """Get the start and end dates of the current usage period defined in OpenMeter's entitlement.

        Current period is defined by the entitlement's currentUsagePeriod.
        If no entitlement is found, None is returned for both dates.
        """
        customer_key = self.get_resource_pool_key(resource_pool_id)
        entitlement = await self.query_customer_entitlement(customer_key, self._feature_key)
        if entitlement is None:
            return None, None
        if not isinstance(entitlement, MeteredEntitlement):
            logger.warning(
                f"Entitlement for customer={customer_key}, feature_key={self._feature_key} is not metered "
                f"(type={entitlement.get('type')}), it has no usage period"
            )
            return None, None
        return entitlement.currentUsagePeriod.from_, entitlement.currentUsagePeriod.to
