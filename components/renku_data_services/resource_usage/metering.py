"""Meteroid event emission for session resource usage metering."""

from datetime import UTC
from enum import StrEnum

import httpx

from renku_data_services.app_config import logging
from renku_data_services.resource_usage.model import Credit, ResourcesRequest

logger = logging.getLogger(__file__)

class MetricCode(StrEnum):
    session_resource_usage = "session_resource_usage"


def _to_meteroid_event(req: ResourcesRequest, costs: dict[int, Credit], metric_code: str) -> dict:
    cost = costs.get(req.resource_class_id, Credit.zero())  # type: ignore[arg-type]
    cu_cost = round(cost.value * (req.capture_interval.total_seconds() / 3600.0), 6)

    properties: dict[str, str] = {
        "cu_cost": str(cu_cost),
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

    return {
        "event_id": f"{req.uid}/{req.capture_date.astimezone(UTC).isoformat()}",
        "code": metric_code,
        "customer_id": f"resource_pool_id-{req.resource_pool_id}",
        "timestamp": req.capture_date.astimezone(UTC).isoformat(),
        "properties": properties,
    }


class MeteringClient:
    """Emits session resource usage events to Meteroid."""

    def __init__(self, endpoint_url: str, token: str) -> None:
        self._endpoint_url = endpoint_url
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def emit(self, requests: list[ResourcesRequest], costs: dict[int, Credit], metric_code: MetricCode) -> None:
        """POST all resource requests as a Meteroid ingest batch. Never raises."""
        events = [
            _to_meteroid_event(r, costs, metric_code)
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
                    logger.info(f"Emitted {len(events)} metering events, status={resp.status_code}: {body}")
        except httpx.HTTPError as ex:
            logger.warning(f"Failed to emit metering events: {ex}", exc_info=ex)
        except Exception as ex:
            logger.warning(f"Unexpected error emitting metering events: {ex}", exc_info=ex)
