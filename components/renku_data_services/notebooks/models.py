"""Basic models for amalthea sessions."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

from pydantic import AliasGenerator, BaseModel, Field, Json, ValidationError

from renku_data_services.errors import errors
from renku_data_services.notebooks.api.amalthea_patches.jupyter_server import user_secrets
from renku_data_services.notebooks.crs import AmaltheaSessionV1Alpha1, JupyterServerV1Alpha1


@dataclass
class SessionEnvVar:
    name: str
    value: str


@dataclass
class SessionUserSecrets:
    mount_path: Path
    user_secret_ids: list[str]


class _AmaltheaSessionAnnotations(BaseModel):
    class Config:
        extra = "allow"
        alias_generator = AliasGenerator(
            alias=lambda field_name: f"renku.io/{field_name}",
        )

    session_launcher_id: str | None = None
    project_id: str | None = None
    user_secrets_mount_path: str | None = None
    user_secrets_ids: Json[list[str]] = "[]"
    env_variable_names: Json[list[str]] = "[]"


class _MetadataValidation(BaseModel):
    class Config:
        extra = "allow"

    name: str
    annotations: _AmaltheaSessionAnnotations
    labels: dict[str, str] = Field(default_factory=dict)
    namespace: str | None = None


class AmaltheaSessionManifest:
    def __init__(self, manifest: AmaltheaSessionV1Alpha1) -> None:
        self._manifest = manifest
        self._metadata = _MetadataValidation.model_validate(self._manifest.metadata)

    def __repr__(self) -> str:
        return f"{self.__class__}(name={self._metadata.name})"

    @property
    def env_vars(self) -> dict[str, SessionEnvVar]:
        output: dict[str, SessionEnvVar] = {}
        for env in self._manifest.spec.session.env:
            if env.value is None:
                continue
            output[env.name] = SessionEnvVar(env.name, env.value)
        return output

    @property
    def requested_env_vars(self) -> dict[str, SessionEnvVar]:
        requested_names = self._metadata.annotations.env_variable_names
        return {ikey: ival for ikey, ival in self.env_vars.items() if ikey in requested_names}
