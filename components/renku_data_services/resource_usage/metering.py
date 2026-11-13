"""OpenMeter event emission for session resource usage metering."""

from datetime import datetime
from typing import Any, Optional, Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError

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


class MeterQueryResponse(BaseModel):
    """Response from OpenMeter meter query."""

    data: list[dict[str, Any]]


class UsagePeriod(BaseModel):
    """Usage period for OpenMeter entitlement."""

    from_: datetime = Field(alias="from")
    to: datetime


class EntitlementQueryResponse(BaseModel):
    """Response from OpenMeter entitlement query."""

    activeFrom: str
    currentUsagePeriod: UsagePeriod
    customerId: str
    customerKey: str
    featureId: str
    featureKey: str
    isSoftLimit: bool
    measureUsageFrom: str
    type: str
    usagePeriod: dict[str, str]


class EntitlementValueQueryResponse(BaseModel):
    """Response from OpenMeter entitlement value query."""

    hasAccess: Optional[bool] = None
    balance: float
    usage: float
    overage: float
    totalAvailableGrantAmount: float
    config: Optional[str] = None
    grantBalances: Optional[dict[str, float]] = None


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
        return _validate(EntitlementQueryResponse, res)

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
        return _validate(EntitlementValueQueryResponse, res)

    def get_resource_pool_key(self, resource_pool_id: int) -> str:
        """Get the OpenMeter customer / subject key for a resource pool."""
        return f"{self._customer_key_prefix}{resource_pool_id}"

    async def get_resource_pool_total_limit(self, resource_pool_id: int) -> Credit:
        """Get the total usage limit for a resource pool from OpenMeter."""
        customer_key = self.get_resource_pool_key(resource_pool_id)
        entitlement_value = await self.query_customer_entitlement_value(customer_key, self._feature_key)
        if entitlement_value is None:
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
        return Credit.from_float(res.data[0].get("value", 0)) if res.data else Credit.zero()

    async def get_current_period(self, resource_pool_id: int) -> tuple[datetime | None, datetime | None]:
        """Get the start and end dates of the current usage period defined in OpenMeter's entitlement.

        Current period is defined by the entitlement's currentUsagePeriod.
        If no entitlement is found, None is returned for both dates.
        """
        customer_key = self.get_resource_pool_key(resource_pool_id)
        entitlement = await self.query_customer_entitlement(customer_key, self._feature_key)
        if entitlement is None:
            return None, None
        else:
            return entitlement.currentUsagePeriod.from_, entitlement.currentUsagePeriod.to
