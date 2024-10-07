# generated by datamodel-codegen:
#   filename:  api.spec.yaml
#   timestamp: 2024-10-03T07:51:44+00:00

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import Field
from renku_data_services.message_queue.apispec_base import BaseAPISpec


class Error(BaseAPISpec):
    code: int = Field(..., example=1404, gt=0)
    detail: Optional[str] = Field(
        None, example="A more detailed optional message showing what the problem was"
    )
    message: str = Field(..., example="Something went wrong - please try again later")


class ErrorResponse(BaseAPISpec):
    error: Error


class Reprovisioning(BaseAPISpec):
    id: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[0-7][0-9A-HJKMNP-TV-Z]{25}$",
    )
    start_date: datetime = Field(
        ...,
        description="The date and time the reprovisioning was started (in UTC and ISO-8601 format)",
        example="2023-11-01T17:32:28Z",
    )


class ReprovisioningStatus(Reprovisioning):
    pass