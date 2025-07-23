"""Basic models for amalthea sessions."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from kubernetes.client import V1Secret
from pydantic import AliasGenerator, BaseModel, Field, Json

from renku_data_services.data_connectors.models import DataConnectorSecret
from renku_data_services.errors.errors import ProgrammingError
from renku_data_services.notebooks.crs import (
    AmaltheaSessionV1Alpha1,
    DataSource,
    ExtraContainer,
    ExtraVolume,
    ExtraVolumeMount,
    InitContainer,
    SecretRef,
    SecretRefWhole,
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

    def key_ref(self, key: str) -> SecretRef:
        """Get an amalthea secret key reference."""
        meta = self.secret.metadata
        if not meta:
            raise ProgrammingError(message="Cannot get reference to a secret that does not have metadata.")
        secret_name = meta.name
        if not secret_name:
            raise ProgrammingError(message="Cannot get reference to a secret that does not have a name.")
        data = self.secret.data or {}
        string_data = self.secret.string_data or {}
        if key not in data and key not in string_data:
            raise KeyError(f"Cannot find the key {key} in the secret with name {secret_name}")
        return SecretRef(key=key, name=secret_name, adopt=self.adopt)

    def ref(self) -> SecretRefWhole:
        """Get an amalthea reference to the whole secret."""
        meta = self.secret.metadata
        if not meta:
            raise ProgrammingError(message="Cannot get reference to a secret that does not have metadata.")
        secret_name = meta.name
        if not secret_name:
            raise ProgrammingError(message="Cannot get reference to a secret that does not have a name.")
        return SecretRefWhole(name=secret_name, adopt=self.adopt)


@dataclass(frozen=True, kw_only=True)
class SessionExtras:
    """Represents things to add to an amalthea session."""

    containers: list[ExtraContainer] | None = None
    data_connector_secrets: dict[str, list[DataConnectorSecret]] | None = None
    data_sources: list[DataSource] | None = None
    init_containers: list[InitContainer] | None = None
    secrets: list[ExtraSecret] | None = None
    volume_mounts: list[ExtraVolumeMount] | None = None
    volumes: list[ExtraVolume] | None = None

    def concat(self, added_extras: "SessionExtras | None") -> "SessionExtras":
        """Concatenates these session extras with more session extras."""
        if added_extras is None:
            return self
        return SessionExtras(
            containers=self._extend_list(self.containers, added_extras.containers),
            data_connector_secrets=self._extend_dict(self.data_connector_secrets, added_extras.data_connector_secrets),
            data_sources=self._extend_list(self.data_sources, added_extras.data_sources),
            init_containers=self._extend_list(self.init_containers, added_extras.init_containers),
            secrets=self._extend_list(self.secrets, added_extras.secrets),
            volume_mounts=self._extend_list(self.volume_mounts, added_extras.volume_mounts),
            volumes=self._extend_list(self.volumes, added_extras.volumes),
        )

    _T = TypeVar("_T")
    _K = TypeVar("_K")

    @staticmethod
    def _extend_list(l1: list[_T] | None, l2: list[_T] | None) -> list[_T] | None:
        res = l1
        if l2 is not None:
            res = res or []
            res.extend(l2)
        return res

    @staticmethod
    def _extend_dict(d1: dict[_K, _T] | None, d2: dict[_K, _T] | None) -> dict[_K, _T] | None:
        res = d1
        if d2 is not None:
            res = res or dict()
            res.update(d2)
        return res
