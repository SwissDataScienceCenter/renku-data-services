"""Custom Resources for environments, mainly kpack."""

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class EnvItem(BaseModel):
    """Environment variable definition."""

    name: str
    value: str


class ResourceRequest(BaseModel):
    """Resource request entry."""

    cpu: str
    memory: str


class K8sResourceRequest(BaseModel):
    """K8s resource request."""

    requests: ResourceRequest
    limits: ResourceRequest


class ImagePullSecret(BaseModel):
    """K8s image pull secret."""

    name: str


class PersistentVolumeReference(BaseModel):
    """Reference to a persistent volume claim."""

    persistentVolumeClaimName: str


class KpackBuilderReference(BaseModel):
    """Refernce to Kpack builder."""

    name: str
    kind: str = "Builder"


class DockerImage(BaseModel):
    """Docker Image."""

    image: str


class DockerImageWithSecret(DockerImage):
    """Docker image with a pull secret."""

    imagePullSecrets: list[ImagePullSecret]


class KpackGitSource(BaseModel):
    """Git repository source."""

    url: str
    revision: str


class KpackBlobSource(BaseModel):
    """Blob/file archive source."""

    url: str
    stripComponents: str


class KpackSource(BaseModel):
    """Kpack files source resource."""

    git: KpackGitSource | None = None
    blob: KpackBlobSource | None = None

    @model_validator(mode="after")
    def validate(self) -> Self:
        """Validate mode data."""
        if bool(self.git) == bool(self.blob):
            raise ValueError("'git' and 'blob' are mutually exclusive and one of them must be set.")
        return self


class KpackBuildCustomization(BaseModel):
    """Customization of a kpack build."""

    env: list[EnvItem]


class KpackImageSpec(BaseModel):
    """KPack image spec model."""

    tag: str
    additionalTags: list[str]
    serviceAccountName: str
    builder: KpackBuilderReference
    source: KpackSource
    build: KpackBuildCustomization
    successBuildHistoryLimit: int = 1
    failedBuildHistoryLimit: int = 1


class KpackImage(BaseModel):
    """Kpack Image resource."""

    model_config = ConfigDict(
        extra="allow",
    )
    kind: str = "Image"
    apiVersion: str = "kpack.io/v1alpha2"
    metadata: Metadata
    spec: KpackImageSpec


class KpackVolumeCache(BaseModel):
    """Persistent volume to serve as cache for kpack build."""

    volume: PersistentVolumeReference


class ImageTagReference(BaseModel):
    """Reference to an image tag."""

    tag: str


class KpackCacheImage(BaseModel):
    """Image definition to use as build cache."""

    registry: ImageTagReference


class KpackBuildSpec(BaseModel):
    """Spec for kpack build."""

    builder: DockerImageWithSecret
    cache: KpackVolumeCache | KpackCacheImage
    env: list[EnvItem]
    resources: K8sResourceRequest
    runImage: DockerImage
    serviceAccountName: str
    source: KpackSource
    tags: list[str]
    activeDeadlineSeconds: int = 1800


class KpackBuild(BaseModel):
    """KPack build resource."""

    model_config = ConfigDict(
        extra="allow",
    )
    kind: str = "Build"
    apiVersion: str = "kpack.io/v1alpha2"
    metadata: Metadata
    spec: KpackBuildSpec
