"""Extra definitions for the API spec."""

from typing import Annotated, Any, Union

from pydantic import Discriminator, Field, RootModel, Tag

from renku_data_services.session.apispec import (
    Build2,
    Build3,
    EnvironmentIdOnlyPatch,
    EnvironmentPatchInLauncher,
)
from renku_data_services.session.apispec import (
    SessionLauncherPatch as _SessionLauncherInPatch,
)


class Build(RootModel[Union[Build2, Build3]]):
    """A build."""

    root: Union[Build2, Build3] = Field(...)


def _env_patch_disc(v: Any) -> str:
    if isinstance(v, dict) and v.get("id") is not None and all([v is None or k == "id" for k, v in v.items()]):
        return "id"
    return "full"


class SessionLauncherPatch(_SessionLauncherInPatch):
    """Modified launcher patch that makes union selection clear."""

    environment: (
        Annotated[
            Union[Annotated[EnvironmentIdOnlyPatch, Tag("id")], Annotated[EnvironmentPatchInLauncher, Tag("full")]],
            Discriminator(_env_patch_disc),
        ]
        | None
    ) = None
