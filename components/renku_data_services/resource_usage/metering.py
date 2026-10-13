"""OpenMeter event emission for session resource usage metering."""

from datetime import UTC
from enum import StrEnum
from typing import Any, Optional, Protocol

import httpx
from pydantic import BaseModel

from renku_data_services.app_config import logging
from renku_data_services.crc.models import ResourceClass
from renku_data_services.errors import errors
from renku_data_services.resource_usage.model import Credit, ResourcePoolLimits, ResourcePoolUsage, ResourcesRequest

logger = logging.getLogger(__file__)


COMPUTE_USAGE_KEY = "compute_units"


class MetricCode(StrEnum):
    """Resource usage metric codes."""

    session_resource_usage = "session_resource_usage"


class ResourceUsageMetering(Protocol):
    """Emits resource usage events to an external metering service."""

    async def emit(
        self,
        requests: list[ResourcesRequest],
        costs: dict[int, Credit],
        classes: dict[int, ResourceClass],
        metric_code: MetricCode,
    ) -> None:
        """Emit resource usage events. Never raises."""
        ...

    async def query_compute_usage(
        self, resource_pool_id: int, user_id: str | None, start_date: str | None = None, end_date: str | None = None
    ) -> float:
        """Query compute usage from the metering service."""
        ...

    async def query_compute_usage_with_limits(
        self, resource_pool_id: int, user_id: str, feature_key: str = COMPUTE_USAGE_KEY
    ) -> ResourcePoolUsage:
        """Query compute usage and limits from the metering service."""
        ...


def _cu_cost(req: ResourcesRequest, costs: dict[int, Credit]) -> str:
    """Calculate the CU cost for a captured resource request."""
    cost = costs.get(req.resource_class_id, Credit.zero())  # type: ignore[arg-type]
    cu_cost = round(cost.value * (req.capture_interval.total_seconds() / 3600.0), 6)
    return str(cu_cost)


def _to_openmeter_event(
    req: ResourcesRequest,
    costs: dict[int, Credit],
    classes: dict[int, ResourceClass],
    metric_code: MetricCode,
) -> dict:
    """Convert a resource request into an OpenMeter CloudEvent."""
    data: dict[str, str] = {
        "cu_cost": _cu_cost(req, costs),
        "user_id": str(req.user_id),
        "resource_pool_id": str(req.resource_pool_id),
        "code": metric_code,
    }
    if req.resource_class_id is not None and req.resource_class_id in classes:
        rc = classes[req.resource_class_id]
        data["resource_class_name"] = str(rc.name)
        data["cpu_amount"] = str(rc.cpu)
        data["gpu_amount"] = str(rc.gpu)
        data["memory_amount"] = str(rc.memory)
        data["default_storage"] = str(rc.default_storage)
        data["max_storage"] = str(rc.max_storage)
    return {
        "id": f"{req.uid}/{req.capture_date.astimezone(UTC).isoformat()}",
        "source": "renku-data-services",
        "specversion": "1.0",
        "type": "renku.compute",
        "subject": f"resource_pool_id-{req.resource_pool_id}",
        "time": req.capture_date.astimezone(UTC).isoformat(),
        "data": data,
    }


class MeterQueryResponse(BaseModel):
    """Response from OpenMeter meter query."""

    data: list[dict[str, Any]]


class EntitlementQueryResponse(BaseModel):
    """Response from OpenMeter entitlement query."""

    activeFrom: str
    currentUsagePeriod: dict[str, str]
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


class OpenMeterClient:
    """Emits session resource usage events to OpenMeter."""

    def __init__(self, endpoint_url: str, token: str) -> None:
        self._endpoint_url = endpoint_url
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = httpx.AsyncClient(timeout=30)

    async def emit(
        self,
        requests: list[ResourcesRequest],
        costs: dict[int, Credit],
        classes: dict[int, ResourceClass],
        metric_code: MetricCode,
    ) -> None:
        """POST all resource requests as an OpenMeter CloudEvents batch. Never raises."""
        headers = {"Content-Type": "application/cloudevents-batch+json", **self._headers}
        events = [
            _to_openmeter_event(r, costs, classes, metric_code)
            for r in requests
            if r.resource_class_id is not None and r.user_id is not None and r.resource_pool_id is not None
        ]
        if not events:
            return
        try:
            resp = await self._client.post(f"{self._endpoint_url}/api/v1/events", headers=headers, json=events)
            if resp.status_code >= 300 or resp.status_code < 200:
                logger.warning(f"OpenMeter endpoint returned unexpected status {resp.status_code}: {resp.text[:200]}")
            else:
                logger.info(f"Emitted {len(events)} metering events to OpenMeter, status={resp.status_code}")
        except httpx.HTTPError as ex:
            logger.warning(f"Failed to emit metering events to OpenMeter: {ex}", exc_info=ex)
        except Exception as ex:
            logger.warning(f"Unexpected error emitting metering events to OpenMeter: {ex}", exc_info=ex)

    async def query_meter(self, meter_id_or_slug: str, body: dict[str, Any]) -> MeterQueryResponse:
        """Query a meter in OpenMeter."""
        resp = await self._client.post(
            f"{self._endpoint_url}/api/v1/meters/{meter_id_or_slug}/query", headers=self._headers, json=body
        )
        if resp.status_code >= 300 or resp.status_code < 200:
            logger.warning(f"OpenMeter endpoint returned unexpected status {resp.status_code}: {resp.text[:200]}")
            raise errors.ThirdPartyAPIError(
                message=f"Received unexpected status code {resp.status_code} when querying OpenMeter meter.",
                detail=f"Message from OpenMeter: {resp.text}",
            )
        return MeterQueryResponse.model_validate(resp.json())

    async def query_compute_usage(
        self,
        resource_pool_id: int,
        user_id: str | None,
        start_date: str | None = None,
        end_date: str | None = None,
        meter_key: str = COMPUTE_USAGE_KEY,
    ) -> float:
        """Query compute usage from OpenMeter.

        If user_id is None, the total usage for the resource pool is returned.
        Otherwise, the usage for the specified user within the resource pool is returned.
        """
        body: dict[str, Any] = {
            "subject": [
                f"renku-pool-{resource_pool_id}",
            ]
        }
        if start_date is not None:
            body["from"] = start_date
        if end_date is not None:
            body["to"] = end_date
        if user_id is not None:
            user_body = {"advancedMeterGroupByFilters": {"user_id": {"$eq": user_id}}, "groupBy": ["user_id"]}
            body.update(user_body)
        res = await self.query_meter(meter_key, body)
        return res.data[0].get("value", 0.0) if res.data else 0.0

    async def query_customer_entitlement(self, customer_id: str, feature_key: str) -> EntitlementQueryResponse | None:
        """Query a customer entitlement in OpenMeter."""
        resp = await self._client.get(
            f"{self._endpoint_url}/api/v2/customers/{customer_id}/entitlements/{feature_key}",
            headers=self._headers,
        )
        if resp.status_code == 404:
            logger.warning(f"No customer or feature found for customer_id={customer_id} and feature_key={feature_key}")
            return None

        if resp.status_code >= 300 or resp.status_code < 200:
            logger.warning(f"OpenMeter endpoint returned unexpected status {resp.status_code}: {resp.text[:200]}")
            raise errors.ThirdPartyAPIError(
                message=f"Received unexpected status code {resp.status_code} when querying OpenMeter entitlement.",
                detail=f"Message from OpenMeter: {resp.text}",
            )
        if resp.json() == {}:
            logger.warning(f"No customer entitlement found for customer_id={customer_id}, feature_key={feature_key}")
            return None

        return EntitlementQueryResponse.model_validate(resp.json())

    async def query_customer_entitlement_value(
        self, customer_id: str, feature_key: str
    ) -> EntitlementValueQueryResponse | None:
        """Query a customer entitlement value in OpenMeter."""
        resp = await self._client.get(
            f"{self._endpoint_url}/api/v2/customers/{customer_id}/entitlements/{feature_key}/value",
            headers=self._headers,
        )
        if resp.status_code == 404:
            logger.warning(f"No customer found for customer_id={customer_id}")
            return None

        if resp.status_code >= 300 or resp.status_code < 200:
            logger.warning(f"OpenMeter endpoint returned unexpected status {resp.status_code}: {resp.text[:200]}")
            raise errors.ThirdPartyAPIError(
                message=f"Received unexpected status code {resp.status_code} when querying OpenMeter entitlement.",
                detail=f"Message from OpenMeter: {resp.text}",
            )
        if resp.json() == {}:
            logger.warning(f"No customer entitlement found for customer_id={customer_id}, feature_key={feature_key}")
            return None

        return EntitlementValueQueryResponse.model_validate(resp.json())

    async def query_compute_usage_with_limits(
        self, resource_pool_id: int, user_id: str, feature_key: str = COMPUTE_USAGE_KEY
    ) -> ResourcePoolUsage:
        """Query compute usage and limits from OpenMeter.

        Assumptions:
        - Customers have only one subject and share the same key `renku-pool-{resource_pool_id}`
        - Feature and meter for compute usage share the same key `compute_units`
        """
        customer_id = f"renku-pool-{resource_pool_id}"
        entitlement = await self.query_customer_entitlement(customer_id, feature_key)
        if entitlement is None:
            # We compute usage over the entire history and return limits with zero values
            user_usage = await self.query_compute_usage(resource_pool_id, user_id, meter_key=feature_key)
            total_usage = await self.query_compute_usage(resource_pool_id, None, meter_key=feature_key)
            limits = ResourcePoolLimits(
                pool_id=resource_pool_id,
                total_limit=Credit.zero(),
                user_limit=Credit.zero(),
            )
            return ResourcePoolUsage(total_usage, user_usage, limits)

        entitlement_value = await self.query_customer_entitlement_value(customer_id, feature_key)
        if entitlement_value is None:
            # If entitlement is not None, it should have a value, otherwise we raise an error
            raise errors.ValidationError(
                message=f"Unexpected entitlement value for customer_id={customer_id} and feature_key={feature_key}.",
                detail=f"Entitlement: {entitlement}",
            )

        start_date = entitlement.currentUsagePeriod["from"]
        end_date = entitlement.currentUsagePeriod["to"]
        user_usage = await self.query_compute_usage(
            resource_pool_id, user_id, start_date, end_date, meter_key=feature_key
        )
        total_usage = entitlement_value.usage
        limits = ResourcePoolLimits(
            pool_id=resource_pool_id,
            total_limit=Credit.from_int(int(entitlement_value.totalAvailableGrantAmount)),
            user_limit=Credit.zero(),  # TODO: check how we can get the user limit
        )
        return ResourcePoolUsage(total_usage, user_usage, limits)
