"""Custom resource definition with proper names from the autogenerated code."""

from datetime import datetime

from pydantic import BaseModel, Field

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


class JupyterServerV1Alpha1(_JSModel):
    """Jupyter server CRD."""

    kind: str = "JupyterServer"
    apiVersion: str = "amalthea.dev/v1alpha1"
    metadata: Metadata


class AmaltheaSessionV1Alpha1(_ASModel):
    """Amalthea session CRD."""

    kind: str = "AmaltheaSession"
    apiVersion: str = "amalthea.dev/v1alpha1"
    # Here we overwrite the default from ASModel because it is too weakly typed
    metadata: Metadata  # type: ignore[assignment]