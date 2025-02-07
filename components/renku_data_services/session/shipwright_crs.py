"""Custom Resources for shipwright environments."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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


class StrategyRef(BaseModel):
    """Reference to a shipwright build strategy."""

    name: str
    kind: str = "ClusterBuildStrategy"


class BuildOutput(BaseModel):
    """Defines the output of a shipwright build."""

    image: str
    pushSecret: str | None


class ConfigMapRef(BaseModel):
    """A reference to a value in a config map."""

    name: str
    key: str


class ParamValue(BaseModel):
    """A value for a build strategy parameter."""

    name: str
    value: str | None
    configMapValue: ConfigMapRef | None


class GitRef(BaseModel):
    """A reference to a git repo."""

    url: str
    revision: str
    cloneSecret: str


class GitSource(BaseModel):
    """A git repo to use as source for a shipwright build."""

    type: str = "Git"
    git: GitRef
    contextDir: str


class Retention(BaseModel):
    """Retention Policy."""

    ttlAfterFailed: str = "1440m"
    ttlAfterSucceeded: str = "60m"
    failedLimit: int = 1
    succeededLimet: int = 1


class BuildSpec(BaseModel):
    """Shipwright build spec."""

    source: GitSource
    paramValues: list[ParamValue]
    strategy: StrategyRef
    output: BuildOutput
    retention: Retention


class Build(BaseModel):
    """A shipwright build."""

    model_config = ConfigDict(
        extra="allow",
    )
    kind: str = "Build"
    apiVersion: str = "shipwright.io/v1beta2"
    metadata: Metadata
    spec: BuildSpec


class InlineBuild(BaseModel):
    """A shipwright build."""

    model_config = ConfigDict(
        extra="allow",
    )
    spec: BuildSpec


class BuildRef(BuildSpec):
    """Reference to a build."""

    name: str


class BuildRunSpec(BaseModel):
    """Spec for a build run."""

    build: BuildRef | InlineBuild


class BuildRun(BaseModel):
    """A shipwright build run."""

    model_config = ConfigDict(
        extra="allow",
    )
    kind: str = "BuildRun"
    apiVersion: str = "shipwright.io/v1beta2"
    metadata: Metadata
    spec: BuildRunSpec
