# generated by datamodel-codegen:
#   filename:  api.spec.yaml
#   timestamp: 2023-12-04T07:56:03+00:00

from __future__ import annotations

from typing import List, Optional

from pydantic import ConfigDict, Field, RootModel

from renku_data_services.user_preferences.apispec_base import BaseAPISpec


class ProjectSlug(RootModel[str]):
    root: str = Field(..., description="The slug used to identify a project", example="user/my-project", min_length=3)


class AddPinnedProject(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    project_slug: str = Field(
        ..., description="The slug used to identify a project", example="user/my-project", min_length=3
    )


class Error(BaseAPISpec):
    code: int = Field(..., example=1404, gt=0)
    detail: Optional[str] = Field(None, example="A more detailed optional message showing what the problem was")
    message: str = Field(..., example="Something went wrong - please try again later")


class ErrorResponse(BaseAPISpec):
    error: Error


class PinnedProjects(BaseAPISpec):
    project_slugs: Optional[List[ProjectSlug]] = None


class UserPreferences(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    user_id: str = Field(..., description="The unique identifier for a user", example="user-id-example", min_length=3)
    pinned_projects: PinnedProjects
