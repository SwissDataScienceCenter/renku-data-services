"""Basic models for amalthea sessions."""

from dataclasses import dataclass
from pathlib import Path

from pydantic import AliasGenerator, BaseModel, Field, Json

from renku_data_services.notebooks.crs import AmaltheaSessionV1Alpha1


@dataclass
class SessionEnvVar:
    """Environment variables for an amalthea session."""

    name: str
    value: str


@dataclass
class SessionUserSecrets:
    """User secret mounted in an amalthea session."""

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
    user_secrets_ids: Json[list[str]] = Field(default_factory=list)
    env_variable_names: Json[list[str]] = Field(default_factory=list)


class _MetadataValidation(BaseModel):
    class Config:
        extra = "allow"

    name: str
    annotations: _AmaltheaSessionAnnotations
    labels: dict[str, str] = Field(default_factory=dict)
    namespace: str | None = None


class AmaltheaSessionManifest:
    """The manifest for an amalthea session."""

    def __init__(self, manifest: AmaltheaSessionV1Alpha1) -> None:
        self._manifest = manifest
        self._metadata = _MetadataValidation.model_validate(self._manifest.metadata)

    def __repr__(self) -> str:
        return f"{self.__class__}(name={self._metadata.name})"

    @property
    def env_vars(self) -> dict[str, SessionEnvVar]:
        """Extract the environment variables from a manifest."""
        output: dict[str, SessionEnvVar] = {}
        assert self._manifest.spec
        for env in self._manifest.spec.session.env or []:
            if env.value is None:
                continue
            output[env.name] = SessionEnvVar(env.name, env.value)
        return output

    @property
    def requested_env_vars(self) -> dict[str, SessionEnvVar]:
        """The environment variables requested."""
        requested_names = self._metadata.annotations.env_variable_names
        return {ikey: ival for ikey, ival in self.env_vars.items() if ikey in requested_names}
