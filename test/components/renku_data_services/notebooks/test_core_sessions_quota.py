"""Tests for the quota check done when launching or resuming sessions."""

from datetime import UTC, datetime
from typing import Any, cast

import pytest

from renku_data_services.errors import errors
from renku_data_services.notebooks.core_sessions import _check_quota
from renku_data_services.resource_usage.core import ResourceUsageService
from renku_data_services.resource_usage.model import Credit, CreditBalance


class _FakeResourceUsageService:
    def __init__(self, result: CreditBalance | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error

    async def get_remaining_quota(self, resource_pool_id: int, user_id: str) -> CreditBalance | None:
        if self.error is not None:
            raise self.error
        return self.result


def _service(**kwargs: Any) -> ResourceUsageService:
    return cast(ResourceUsageService, _FakeResourceUsageService(**kwargs))


RESET_AT = datetime(2026, 11, 23, tzinfo=UTC)


@pytest.mark.parametrize(
    "service",
    [
        _service(result=None),
        _service(result=CreditBalance(Credit.from_int(10), RESET_AT)),
        _service(error=errors.ThirdPartyAPIError(message="OpenMeter is down")),
    ],
    ids=["no-limit", "remaining", "metering-unavailable"],
)
async def test_check_quota_allows_session(service: ResourceUsageService) -> None:
    """Sessions can start when there is quota left, no limit, or the metering service is unavailable."""
    await _check_quota(service, resource_pool_id=1, user_id="user")


async def test_check_quota_exhausted() -> None:
    """Sessions cannot start when the quota is exhausted."""
    service = _service(result=CreditBalance(Credit.zero(), RESET_AT))
    with pytest.raises(errors.ValidationError):
        await _check_quota(service, resource_pool_id=1, user_id="user")
