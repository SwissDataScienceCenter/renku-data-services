"""Custom resource definition with proper names from the autogenerated code."""

from datetime import datetime
from typing import Any, cast
from urllib.parse import urlunparse

from kubernetes.utils import parse_duration, parse_quantity
from pydantic import BaseModel, Field, field_validator
from ulid import ULID

from renku_data_services.errors import errors
from renku_data_services.notebooks import apispec
from renku_data_services.notebooks.cr_amalthea_session import (
    Affinity,
    Authentication,
    CodeRepository,
    Culling,
    DataSource,
    EmptyDir,
    ExtraContainer,
    ExtraVolume,
    ExtraVolumeMount,
    Ingress,
    InitContainer,
    MatchExpression,
    NodeAffinity,
    NodeSelectorTerm,
    Preference,
    PreferredDuringSchedulingIgnoredDuringExecutionItem,
    ReconcileStrategy,
    RequiredDuringSchedulingIgnoredDuringExecution,
    SecretRef,
    Session,
    Spec,
    State,
    Status,
    Storage,
    TlsSecret,
    Toleration,
)
from renku_data_services.notebooks.cr_amalthea_session import EnvItem2 as SessionEnvItem
from renku_data_services.notebooks.cr_amalthea_session import Item4 as SecretAsVolumeItem
from renku_data_services.notebooks.cr_amalthea_session import Model as _ASModel
from renku_data_services.notebooks.cr_amalthea_session import Resources3 as Resources
from renku_data_services.notebooks.cr_amalthea_session import Secret1 as SecretAsVolume
from renku_data_services.notebooks.cr_amalthea_session import SecretRef as SecretRefKey
from renku_data_services.notebooks.cr_amalthea_session import SecretRef1 as SecretRefWhole
from renku_data_services.notebooks.cr_amalthea_session import Spec as AmaltheaSessionSpec
from renku_data_services.notebooks.cr_amalthea_session import Type as AuthenticationType
from renku_data_services.notebooks.cr_amalthea_session import Type1 as CodeRepositoryType
from renku_data_services.notebooks.cr_base import BaseCRD
from renku_data_services.notebooks.cr_jupyter_server import Model as _JSModel
from renku_data_services.notebooks.cr_jupyter_server import Patch
from renku_data_services.notebooks.cr_jupyter_server import Spec as JupyterServerSpec
from renku_data_services.notebooks.cr_jupyter_server import Type as PatchType


class Metadata(BaseModel):
    """Basic k8s metadata spec."""

    class Config:
        """Do not exclude unknown properties."""

        extra = "allow"

    name: str
    namespace: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    uid: str | None = None
    creationTimestamp: datetime | None = None
    deletionTimestamp: datetime | None = None


class ComputeResources(BaseModel):
    """Resource requests from k8s values."""

    cpu: float | None = None
    memory: int | None = None
    storage: int | None = None
    gpu: int | None = None

    @field_validator("cpu", mode="before")
    @classmethod
    def _convert_k8s_cpu(cls, val: Any) -> Any:
        if val is None:
            return None
        return float(parse_quantity(val))

    @field_validator("gpu", mode="before")
    @classmethod
    def _convert_k8s_gpu(cls, val: Any) -> Any:
        if val is None:
            return None
        return round(parse_quantity(val), ndigits=None)

    @field_validator("memory", "storage", mode="before")
    @classmethod
    def _convert_k8s_bytes(cls, val: Any) -> Any:
        """Converts to gigabytes of base 10."""
        if val is None:
            return None
        return round(parse_quantity(val) / 1_000_000_000, ndigits=None)


class JupyterServerV1Alpha1(_JSModel):
    """Jupyter server CRD."""

    kind: str = "JupyterServer"
    apiVersion: str = "amalthea.dev/v1alpha1"
    metadata: Metadata

    def get_compute_resources(self) -> ComputeResources:
        """Convert the k8s resource requests and storage into usable values."""
        if self.spec is None:
            return ComputeResources()
        resource_requests: dict = self.spec.jupyterServer.resources.get("requests", {})
        resource_requests["storage"] = self.spec.storage.size
        return ComputeResources.model_validate(resource_requests)


class AmaltheaSessionV1Alpha1(_ASModel):
    """Amalthea session CRD."""

    kind: str = "AmaltheaSession"
    apiVersion: str = "amalthea.dev/v1alpha1"
    # Here we overwrite the default from ASModel because it is too weakly typed
    metadata: Metadata  # type: ignore[assignment]

    def get_compute_resources(self) -> ComputeResources:
        """Convert the k8s resource requests and storage into usable values."""
        if self.spec is None:
            return ComputeResources()
        resource_requests: dict = {}
        if self.spec.session.resources is not None:
            resource_requests = self.spec.session.resources.requests or {}
        resource_requests["storage"] = self.spec.session.storage.size
        return ComputeResources.model_validate(resource_requests)

    @property
    def project_id(self) -> ULID:
        """Get the project ID from the annotations."""
        if "renku.io/project_id" not in self.metadata.annotations:
            raise errors.ProgrammingError(
                message=f"The session with name {self.metadata.name} is missing its project_id annotation"
            )
        return cast(ULID, ULID.from_str(self.metadata.annotations["renku.io/project_id"]))

    @property
    def launcher_id(self) -> ULID:
        """Get the launcher ID from the annotations."""
        if "renku.io/launcher_id" not in self.metadata.annotations:
            raise errors.ProgrammingError(
                message=f"The session with name {self.metadata.name} is missing its launcher_id annotation"
            )
        return cast(ULID, ULID.from_str(self.metadata.annotations["renku.io/launcher_id"]))

    @property
    def resource_class_id(self) -> int:
        """Get the resource class from the annotations."""
        if "renku.io/resource_class_id" not in self.metadata.annotations:
            raise errors.ProgrammingError(
                message=f"The session with name {self.metadata.name} is missing its resource_class_id annotation"
            )
        return int(self.metadata.annotations["renku.io/resource_class_id"])

    def as_apispec(self) -> apispec.SessionResponse:
        """Convert the manifest into a form ready to be serialized and sent in a HTTP response."""
        if self.status is None:
            raise errors.ProgrammingError(
                message=f"The manifest for a session with name {self.metadata.name} cannot be serialized "
                f"because it is missing a status"
            )
        if self.spec is None:
            raise errors.ProgrammingError(
                message=f"The manifest for a session with name {self.metadata.name} cannot be serialized "
                "because it is missing the spec field"
            )
        if self.spec.session.resources is None:
            raise errors.ProgrammingError(
                message=f"The manifest for a session with name {self.metadata.name} cannot be serialized "
                "because it is missing the spec.session.resources field"
            )
        url = "None"
        if self.base_url is not None:
            url = self.base_url
        ready_containers = 0
        total_containers = 0
        if self.status.initContainerCounts is not None:
            ready_containers += self.status.initContainerCounts.ready or 0
            total_containers += self.status.initContainerCounts.total or 0
        if self.status.containerCounts is not None:
            ready_containers += self.status.containerCounts.ready or 0
            total_containers += self.status.containerCounts.total or 0

        if self.status.state in [State.Running, State.Hibernated, State.Failed]:
            state = apispec.State3(self.status.state.value.lower())
        elif self.status.state == State.RunningDegraded:
            state = apispec.State3.running
        elif self.status.state == State.NotReady and self.metadata.deletionTimestamp is not None:
            state = apispec.State3.stopping
        else:
            state = apispec.State3.starting

        will_hibernate_at: datetime | None = None
        will_delete_at: datetime | None = None
        match self.status, self.spec.culling:
            case (
                Status(idle=True, idleSince=idle_since),
                Culling(maxIdleDuration=max_idle),
            ) if idle_since and max_idle:
                will_hibernate_at = idle_since + parse_duration(max_idle)
            case (
                Status(state=State.Failed, failingSince=failing_since),
                Culling(maxFailedDuration=max_failed),
            ) if failing_since and max_failed:
                will_hibernate_at = failing_since + parse_duration(max_failed)
            case (
                Status(state=State.NotReady),
                Culling(maxAge=max_age),
            ) if max_age and self.metadata.creationTimestamp:
                will_hibernate_at = self.metadata.creationTimestamp + parse_duration(max_age)
            case (
                Status(state=State.Hibernated, hibernatedSince=hibernated_since),
                Culling(maxHibernatedDuration=max_hibernated),
            ) if hibernated_since and max_hibernated:
                will_delete_at = hibernated_since + parse_duration(max_hibernated)

        return apispec.SessionResponse(
            image=self.spec.session.image,
            name=self.metadata.name,
            resources=apispec.SessionResources(
                requests=apispec.SessionResourcesRequests.model_validate(
                    self.get_compute_resources(), from_attributes=True
                )
                if self.spec.session.resources.requests is not None
                else None,
            ),
            started=self.metadata.creationTimestamp,
            status=apispec.SessionStatus(
                state=state,
                ready_containers=ready_containers,
                total_containers=total_containers,
                will_hibernate_at=will_hibernate_at,
                will_delete_at=will_delete_at,
                message=self.status.error,
            ),
            url=url,
            project_id=str(self.project_id),
            launcher_id=str(self.launcher_id),
            resource_class_id=self.resource_class_id,
        )

    @property
    def base_url(self) -> str | None:
        """Get the URL of the session, excluding the default URL from the session launcher."""
        if self.status.url and len(self.status.url) > 0:
            return self.status.url
        if self.spec is None or self.spec.ingress is None:
            return None
        scheme = "https" if self.spec and self.spec.ingress and self.spec.ingress.tlsSecret else "http"
        host = self.spec.ingress.host
        path = self.spec.session.urlPath if self.spec.session.urlPath else "/"
        if not path.endswith("/"):
            path += "/"
        params = None
        query = None
        fragment = None
        url = urlunparse((scheme, host, path, params, query, fragment))
        return url


class AmaltheaSessionV1Alpha1SpecSessionPatch(BaseCRD):
    """Patch for the main session config."""

    resources: Resources | None = None
    shmSize: int | str | None = None
    storage: Storage | None = None


class AmaltheaSessionV1Alpha1SpecPatch(BaseCRD):
    """Patch for the spec of an amalthea session."""

    extraContainers: list[ExtraContainer] | None = None
    extraVolumes: list[ExtraVolume] | None = None
    hibernated: bool | None = None
    initContainers: list[InitContainer] | None = None
    priorityClassName: str | None = None
    tolerations: list[Toleration] | None = None
    affinity: Affinity | None = None
    session: AmaltheaSessionV1Alpha1SpecSessionPatch | None = None


class AmaltheaSessionV1Alpha1Patch(BaseCRD):
    """Patch for an amalthea session."""

    spec: AmaltheaSessionV1Alpha1SpecPatch

    def to_rfc7386(self) -> dict[str, Any]:
        """Generate the patch to be applied to the session."""
        return self.model_dump(exclude_none=True)
