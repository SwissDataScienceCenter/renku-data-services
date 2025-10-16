"""Basic models for amalthea sessions."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from kubernetes.client import V1ObjectMeta, V1Secret
from pydantic import AliasGenerator, BaseModel, Field, Json
from ulid import ULID

from renku_data_services.data_connectors.models import DataConnectorSecret
from renku_data_services.errors import errors
from renku_data_services.errors.errors import ProgrammingError
from renku_data_services.notebooks.api.schemas.cloud_storage import RCloneStorageRequestOverride
from renku_data_services.notebooks.crs import (
    AmaltheaSessionV1Alpha1,
    DataSource,
    ExtraContainer,
    ExtraVolume,
    ExtraVolumeMount,
    InitContainer,
    SecretRef,
)


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


@dataclass
class ExtraSecret:
    """Specification for a K8s secret and its coresponding volumes and mounts."""

    secret: V1Secret = field(repr=False)
    volume: ExtraVolume | None = None
    volume_mount: ExtraVolumeMount | None = None
    adopt: bool = True

    def __post_init__(self) -> None:
        if not self.secret.metadata:
            raise errors.ValidationError(message="The secret in Extra secret is missing its metadata.")
        if isinstance(self.secret.metadata, V1ObjectMeta):
            secret_name = cast(str | None, self.secret.metadata.name)
        else:
            secret_name = cast(str | None, self.secret.metadata.get("name"))
        if not isinstance(secret_name, str):
            raise errors.ValidationError(message="The secret name in Extra secret is not a string.")
        if len(secret_name) == 0:
            raise errors.ValidationError(message="The secret name in Extra secret is empty.")
        self.__secret_name = secret_name

    def key_ref(self, key: str | None = None) -> SecretRef:
        """Get an amalthea secret key reference."""
        meta = self.secret.metadata
        if not meta:
            raise ProgrammingError(message="Cannot get reference to a secret that does not have metadata.")
        secret_name = meta.name
        if not secret_name:
            raise ProgrammingError(message="Cannot get reference to a secret that does not have a name.")
        data = self.secret.data or {}
        string_data = self.secret.string_data or {}
        if key is not None and key not in data and key not in string_data:
            raise KeyError(f"Cannot find the key {key} in the secret with name {secret_name}")
        return SecretRef(key=key, name=secret_name, adopt=self.adopt)

    def ref(self) -> SecretRef:
        """Get an amalthea reference to the whole secret."""
        meta = self.secret.metadata
        if not meta:
            raise ProgrammingError(message="Cannot get reference to a secret that does not have metadata.")
        secret_name = meta.name
        if not secret_name:
            raise ProgrammingError(message="Cannot get reference to a secret that does not have a name.")
        return SecretRef(name=secret_name, adopt=self.adopt)

    @property
    def name(self) -> str:
        """Return the name of the secret."""
        return self.__secret_name


@dataclass(frozen=True, kw_only=True)
class SessionExtraResources:
    """Represents extra resources to add to an amalthea session."""

    annotations: dict[str, str] = field(default_factory=dict)
    containers: list[ExtraContainer] = field(default_factory=list)
    data_connector_secrets: dict[str, list[DataConnectorSecret]] = field(default_factory=dict)
    data_sources: list[DataSource] = field(default_factory=list)
    init_containers: list[InitContainer] = field(default_factory=list)
    secrets: list[ExtraSecret] = field(default_factory=list)
    volume_mounts: list[ExtraVolumeMount] = field(default_factory=list)
    volumes: list[ExtraVolume] = field(default_factory=list)

    def concat(self, added_extras: "SessionExtraResources | None") -> "SessionExtraResources":
        """Concatenates these session extras with more session extras."""
        if added_extras is None:
            return self
        annotations: dict[str, str] = dict()
        annotations.update(self.annotations)
        annotations.update(added_extras.annotations)
        data_connector_secrets: dict[str, list[DataConnectorSecret]] = dict()
        data_connector_secrets.update(self.data_connector_secrets)
        data_connector_secrets.update(added_extras.data_connector_secrets)
        return SessionExtraResources(
            annotations=annotations,
            containers=self.containers + added_extras.containers,
            data_connector_secrets=data_connector_secrets,
            data_sources=self.data_sources + added_extras.data_sources,
            init_containers=self.init_containers + added_extras.init_containers,
            secrets=self.secrets + added_extras.secrets,
            volume_mounts=self.volume_mounts + added_extras.volume_mounts,
            volumes=self.volumes + added_extras.volumes,
        )


@dataclass(eq=True, kw_only=True)
class SessionDataConnectorOverride(RCloneStorageRequestOverride):
    """Model for a data connector override."""

    skip: bool
    data_connector_id: ULID
    configuration: dict[str, Any] | None
    source_path: str | None
    target_path: str | None
    readonly: bool | None


@dataclass(frozen=True, eq=True, kw_only=True)
class SessionLaunchRequest:
    """Model for requesting a session launch."""

    launcher_id: ULID
    disk_storage: int | None
    resource_class_id: int | None
    # data_connectors_overrides: Optional[List[SessionDataConnectorsOverride]] = None
    data_connectors_overrides: list[SessionDataConnectorOverride] | None
    env_variable_overrides: list[SessionEnvVar] | None
