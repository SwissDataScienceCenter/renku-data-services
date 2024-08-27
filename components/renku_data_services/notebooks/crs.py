"""Custom resource definition with proper names from the autogenerated code."""

from datetime import datetime
from typing import Any, cast
from urllib.parse import urljoin

from kubernetes.utils import parse_quantity
from pydantic import BaseModel, Field, field_validator
from sanic.log import logger
from ulid import ULID

from renku_data_services.errors import errors
from renku_data_services.notebooks import apispec
from renku_data_services.notebooks.cr_amalthea_session import (
    Authentication,
    CodeRepository,
    Culling,
    DataSource,
    ExtraContainer,
    ExtraVolume,
    ExtraVolumeMount,
    Ingress,
    InitContainer,
    SecretRef,
    Session,
    Storage,
)
from renku_data_services.notebooks.cr_amalthea_session import EnvItem2 as SessionEnvItem
from renku_data_services.notebooks.cr_amalthea_session import Item4 as SecretAsVolumeItem
from renku_data_services.notebooks.cr_amalthea_session import Model as _ASModel
from renku_data_services.notebooks.cr_amalthea_session import Resources3 as Resources
from renku_data_services.notebooks.cr_amalthea_session import Secret1 as SecretAsVolume
from renku_data_services.notebooks.cr_amalthea_session import Spec as AmaltheaSessionSpec
from renku_data_services.notebooks.cr_amalthea_session import Type as AuthenticationType
from renku_data_services.notebooks.cr_amalthea_session import Type1 as CodeRepositoryType
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
        if self.status.url is None or self.status.url == "" or self.status.url.lower() == "None":
            if self.spec is not None and self.spec.ingress is not None:
                scheme = "https" if self.spec.ingress.tlsSecretName is not None else "http"
                url = urljoin(f"{scheme}://{self.spec.ingress.host}", self.spec.session.urlPath)
        else:
            url = self.status.url
        ready_containers = 0
        total_containers = 0
        if self.status.initContainerCounts is not None:
            ready_containers += self.status.initContainerCounts.ready or 0
            total_containers += self.status.initContainerCounts.total or 0
        if self.status.containerCounts is not None:
            ready_containers += self.status.containerCounts.ready or 0
            total_containers += self.status.containerCounts.total or 0
        return apispec.SessionResponse(
            image=self.spec.session.image,
            name=self.metadata.name,
            resources=apispec.SessionResources(
                requests=apispec.SessionResourcesRequests.model_validate(
                    self.spec.session.resources.requests, from_attributes=True
                )
                if self.spec.session.resources.requests is not None
                else None,
            ),
            started=self.metadata.creationTimestamp,
            status=apispec.SessionStatus(
                state=apispec.State3.running,
                ready_containers=ready_containers,
                total_containers=total_containers,
            ),
            url=url,
            project_id=str(self.project_id),
            launcher_id=str(self.launcher_id),
            resource_class_id=self.resource_class_id,
        )
