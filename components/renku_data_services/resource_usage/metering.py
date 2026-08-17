"""Meteroid event emission for session resource usage metering."""

from collections.abc import Sequence
from datetime import UTC
from enum import StrEnum
from typing import Protocol

from components.renku_data_services.crc.models import ResourceClass
import httpx

from renku_data_services.app_config import logging
from renku_data_services.resource_usage.model import Credit, ResourcesRequest

logger = logging.getLogger(__file__)


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


def _cu_cost(req: ResourcesRequest, costs: dict[int, Credit]) -> str:
    """Calculate the CU cost for a captured resource request."""
    cost = costs.get(req.resource_class_id, Credit.zero())  # type: ignore[arg-type]
    cu_cost = round(cost.value * (req.capture_interval.total_seconds() / 3600.0), 6)
    return str(cu_cost)


def _to_meteroid_event(
    req: ResourcesRequest, costs: dict[int, Credit], classes: dict[int, ResourceClass], metric_code: MetricCode
) -> dict:
    properties: dict[str, str] = {
        "cu_cost": _cu_cost(req, costs),
        "kind": req.kind,
        "phase": req.phase,
        "capture_interval_seconds": str(req.capture_interval.total_seconds()),
        "resource_class_id": str(req.resource_class_id),
        "user_id": str(req.user_id),
    }
    if req.resource_pool_id is not None:
        properties["resource_pool_id"] = str(req.resource_pool_id)
    if req.project_id is not None:
        properties["project_id"] = str(req.project_id)
    if req.launcher_id is not None:
        properties["launcher_id"] = str(req.launcher_id)
    if req.cluster_id is not None:
        properties["cluster_id"] = str(req.cluster_id)
    if req.resource_class_id is not None and req.resource_class_id in classes:
        rc = classes[req.resource_class_id]
        properties["cpu_amount"] = str(rc.cpu)
        properties["gpu_amount"] = str(rc.gpu)
        properties["memory_amount"] = str(rc.memory)
        properties["default_storage"] = str(rc.default_storage)
        properties["max_storage"] = str(rc.max_storage)
        properties["resource_class_name"] = str(rc.name)
    if req.gpu_product is not None:
        properties["gpu_product"] = str(req.gpu_product)
    if req.gpu_slice is not None:
        properties["gpu_slice"] = str(req.gpu_slice)

    return {
        "event_id": f"{req.uid}/{req.capture_date.astimezone(UTC).isoformat()}",
        "code": metric_code,
        "customer_id": f"resource_pool_id-{req.resource_pool_id}",
        "timestamp": req.capture_date.astimezone(UTC).isoformat(),
        "properties": properties,
    }


def _external_subscription_id(req: ResourcesRequest) -> str:
    """Return the Lago subscription identifier for a resource request."""
    return f"resource_pool_id-{req.resource_pool_id}"


def _to_lago_event(
    req: ResourcesRequest,
    costs: dict[int, Credit],
    classes: dict[int, ResourceClass],
) -> dict:
    """Convert a resource request into a Lago usage event."""
    return {
        "transaction_id": f"{req.uid}/{req.capture_date.astimezone(UTC).isoformat()}",
        "external_subscription_id": _external_subscription_id(req),
        "code": "compute_resource_usage",
        "properties": {"cu_cost": _cu_cost(req, costs)},
    }


class MeteringClient:
    """Emits session resource usage events to Meteroid."""

    def __init__(self, endpoint_url: str, token: str) -> None:
        self._endpoint_url = endpoint_url
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def emit(
        self,
        requests: list[ResourcesRequest],
        costs: dict[int, Credit],
        classes: dict[int, ResourceClass],
        metric_code: MetricCode,
    ) -> None:
        """POST all resource requests as a Meteroid ingest batch. Never raises."""
        events = [
            _to_meteroid_event(r, costs, classes, metric_code)
            for r in requests
            if r.resource_class_id is not None and r.user_id is not None and r.resource_pool_id is not None
        ]
        if not events:
            return
        body = {"allow_partial_failures": True, "events": events}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(self._endpoint_url, headers=self._headers, json=body)
                if resp.status_code >= 300 or resp.status_code < 200:
                    logger.warning(
                        f"Metering endpoint returned unexpected status {resp.status_code}: {resp.text[:200]}"
                    )
                else:
                    logger.info(f"Emitted {len(events)} metering events, status={resp.status_code}")
        except httpx.HTTPError as ex:
            logger.warning(f"Failed to emit metering events: {ex}", exc_info=ex)
        except Exception as ex:
            logger.warning(f"Unexpected error emitting metering events: {ex}", exc_info=ex)


class LagoClient:
    """Emits resource usage events to Lago."""

    def __init__(self, endpoint_url: str, token: str) -> None:
        self._endpoint_url = endpoint_url
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def emit(
        self,
        requests: list[ResourcesRequest],
        costs: dict[int, Credit],
        classes: dict[int, ResourceClass],
        metric_code: MetricCode,
    ) -> None:
        """POST resource requests as Lago usage events. Never raises."""
        events = [
            _to_lago_event(r, costs, classes)
            for r in requests
            if r.resource_class_id is not None and r.user_id is not None and r.resource_pool_id is not None
        ]
        if not events:
            return
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                for event in events:
                    body = {"event": event}
                    resp = await client.post(self._endpoint_url, headers=self._headers, json=body)
                    if resp.status_code >= 300 or resp.status_code < 200:
                        logger.warning(
                            f"Lago endpoint returned unexpected status {resp.status_code}: {resp.text[:200]}"
                        )
                    else:
                        logger.info(f"Emitted Lago metering event, status={resp.status_code}: {body}")
        except httpx.HTTPError as ex:
            logger.warning(f"Failed to emit Lago metering events: {ex}", exc_info=ex)
        except Exception as ex:
            logger.warning(f"Unexpected error emitting Lago metering events: {ex}", exc_info=ex)


class MultiMeteringClient:
    """Emits resource usage events to multiple metering services."""

    def __init__(self, clients: Sequence[ResourceUsageMetering]) -> None:
        self._clients = clients

    async def emit(
        self,
        requests: list[ResourcesRequest],
        costs: dict[int, Credit],
        classes: dict[int, ResourceClass],
        metric_code: MetricCode,
    ) -> None:
        """Emit resource usage events to all configured metering services."""
        for client in self._clients:
            await client.emit(requests, costs, classes, metric_code)
