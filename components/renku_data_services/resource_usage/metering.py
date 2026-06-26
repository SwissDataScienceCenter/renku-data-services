"""CloudEvent emission for session resource usage metering."""

from datetime import UTC

import httpx

from renku_data_services.app_config import logging
from renku_data_services.resource_usage.model import Credit, ResourcesRequest

logger = logging.getLogger(__file__)

_CLOUDEVENTS_BATCH_CONTENT_TYPE = "application/cloudevents-batch+json"
_CLOUDEVENTS_DATA_CONTENT_TYPE = "application/json"
_CLOUDEVENTS_SPEC_VERSION = "1.0"
_CLOUDEVENTS_SOURCE = "/renku-data-services/resource-usage"
_CLOUDEVENTS_TYPE = "ch.renku.session.resource_usage"


def _to_cloudevent(req: ResourcesRequest, costs: dict[int, Credit]) -> dict:
    cu_cost: float | None = None
    if req.resource_class_id is not None:
        cost = costs.get(req.resource_class_id, Credit.zero())
        cu_cost = round(cost.value * (req.capture_interval.total_seconds() / 3600.0), 6)

    event: dict = {
        "specversion": _CLOUDEVENTS_SPEC_VERSION,
        "type": _CLOUDEVENTS_TYPE,
        "source": _CLOUDEVENTS_SOURCE,
        "id": f"{req.uid}/{req.capture_date.astimezone(UTC).isoformat()}",
        "time": req.capture_date.astimezone(UTC).isoformat(),
        "datacontenttype": _CLOUDEVENTS_DATA_CONTENT_TYPE,
        "data": {
            "uid": req.uid,
            "kind": req.kind,
            "project_id": str(req.project_id) if req.project_id is not None else None,
            "launcher_id": str(req.launcher_id) if req.launcher_id is not None else None,
            "resource_class_id": req.resource_class_id,
            "resource_pool_id": req.resource_pool_id,
            "cluster_id": str(req.cluster_id) if req.cluster_id is not None else None,
            "phase": req.phase,
            "capture_interval_seconds": req.capture_interval.total_seconds(),
            "cu_cost": cu_cost,
        },
    }
    if req.user_id is not None:
        event["subject"] = req.user_id
    return event


class MeteringClient:
    """Emits session resource usage as CloudEvents to a metering endpoint."""

    def __init__(self, endpoint_url: str, token: str) -> None:
        self._endpoint_url = endpoint_url
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": _CLOUDEVENTS_BATCH_CONTENT_TYPE,
        }

    async def emit(self, requests: list[ResourcesRequest], costs: dict[int, Credit]) -> None:
        """POST all resource requests as a CloudEvents batch. Never raises."""
        if not requests:
            return
        events = [_to_cloudevent(r, costs) for r in requests if r.resource_class_id is not None]
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(self._endpoint_url, headers=self._headers, json=events)
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
