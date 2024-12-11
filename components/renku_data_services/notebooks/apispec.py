# generated by datamodel-codegen:
#   filename:  api.spec.yaml
#   timestamp: 2024-12-11T13:03:50+00:00

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import ConfigDict, Field, RootModel
from renku_data_services.notebooks.apispec_base import BaseAPISpec


class Type(Enum):
    enum = "enum"
    boolean = "boolean"


class BoolServerOptionsChoice(BaseAPISpec):
    default: bool
    displayName: str
    order: int
    type: Type


class CullingThreshold(BaseAPISpec):
    hibernation: int
    idle: int


class DefaultCullingThresholds(BaseAPISpec):
    anonymous: CullingThreshold
    registered: CullingThreshold


class Error(BaseAPISpec):
    code: int = Field(..., example=1404, gt=0)
    detail: Optional[str] = Field(
        None, example="A more detailed optional message showing what the problem was"
    )
    message: str = Field(..., example="Something went wrong - please try again later")


class ErrorResponse(BaseAPISpec):
    error: Error


class Generated(BaseAPISpec):
    enabled: bool


class LaunchNotebookRequestRepository(BaseAPISpec):
    url: str
    dirname: Optional[str] = None
    branch: Optional[str] = None
    commit_sha: Optional[str] = None


class LaunchNotebookRequestServerOptions(BaseAPISpec):
    cpu_request: Any = 0
    defaultUrl: str = "/lab"
    disk_request: Any = "1G"
    gpu_request: Any = 0
    lfs_auto_fetch: bool = False
    mem_request: Any = "0G"


class LaunchNotebookResponseCloudStorage(BaseAPISpec):
    mount_folder: Optional[Any] = None
    remote: Optional[Any] = None
    type: Optional[Any] = None


class NotebooksServiceInfo(BaseAPISpec):
    anonymousSessionsEnabled: bool
    cloudstorageEnabled: bool
    defaultCullingThresholds: DefaultCullingThresholds
    sshEnabled: bool


class NotebooksServiceVersions(BaseAPISpec):
    data: NotebooksServiceInfo
    version: str


class State(Enum):
    running = "running"
    hibernated = "hibernated"


class PatchServerRequest(BaseAPISpec):
    resource_class_id: Optional[int] = None
    state: Optional[State] = None


class RCloneStorageRequest(BaseAPISpec):
    configuration: Optional[Dict[str, Any]] = None
    readonly: bool = True
    source_path: Optional[str] = None
    storage_id: Optional[str] = None
    target_path: Optional[str] = None


class ResourceRequests(BaseAPISpec):
    cpu: Any
    gpu: Optional[Any] = None
    memory: Any
    storage: Optional[Any] = None


class ResourceUsage(BaseAPISpec):
    cpu: Optional[Any] = None
    memory: Optional[Any] = None
    storage: Optional[Any] = None


class ServerLogs(BaseAPISpec):
    model_config = ConfigDict(
        extra="allow",
    )
    jupyter_server: Optional[str] = Field(None, alias="jupyter-server")


class State1(Enum):
    running = "running"
    starting = "starting"
    stopping = "stopping"
    failed = "failed"
    hibernated = "hibernated"


class Status(Enum):
    ready = "ready"
    waiting = "waiting"
    executing = "executing"
    failed = "failed"


class ServerStatusDetail(BaseAPISpec):
    status: Status
    step: str


class ServerStatusWarning(BaseAPISpec):
    critical: bool = False
    message: str


class StringServerOptionsChoice(BaseAPISpec):
    default: str
    displayName: str
    options: Optional[List[str]] = None
    order: int
    type: Type


class UserPodResources(BaseAPISpec):
    requests: Optional[ResourceRequests] = None
    usage: Optional[ResourceUsage] = None


class UserSecrets(BaseAPISpec):
    mount_path: Any
    user_secret_ids: List


class FieldUserPodAnnotations(BaseAPISpec):
    model_config = ConfigDict(
        extra="allow",
    )
    jupyter_org_servername: Optional[str] = Field(None, alias="jupyter.org/servername")
    jupyter_org_username: Optional[str] = Field(None, alias="jupyter.org/username")
    renku_io_branch: str = Field(..., alias="renku.io/branch")
    renku_io_commit_sha: str = Field(..., alias="renku.io/commit-sha")
    renku_io_default_image_used: str = Field(..., alias="renku.io/default_image_used")
    renku_io_git_host: Optional[str] = Field(None, alias="renku.io/git-host")
    renku_io_gitlabProjectId: Optional[str] = Field(
        None, alias="renku.io/gitlabProjectId"
    )
    renku_io_hibernatedSecondsThreshold: Optional[str] = Field(
        None, alias="renku.io/hibernatedSecondsThreshold"
    )
    renku_io_hibernation: Optional[str] = Field(None, alias="renku.io/hibernation")
    renku_io_hibernationBranch: Optional[str] = Field(
        None, alias="renku.io/hibernationBranch"
    )
    renku_io_hibernationCommitSha: Optional[str] = Field(
        None, alias="renku.io/hibernationCommitSha"
    )
    renku_io_hibernationDate: Optional[str] = Field(
        None, alias="renku.io/hibernationDate"
    )
    renku_io_hibernationDirty: Optional[str] = Field(
        None, alias="renku.io/hibernationDirty"
    )
    renku_io_hibernationSynchronized: Optional[str] = Field(
        None, alias="renku.io/hibernationSynchronized"
    )
    renku_io_idleSecondsThreshold: Optional[str] = Field(
        None, alias="renku.io/idleSecondsThreshold"
    )
    renku_io_lastActivityDate: Optional[str] = Field(
        None, alias="renku.io/lastActivityDate"
    )
    renku_io_launcherId: Optional[str] = Field(None, alias="renku.io/launcherId")
    renku_io_namespace: str = Field(..., alias="renku.io/namespace")
    renku_io_projectId: Optional[str] = Field(None, alias="renku.io/projectId")
    renku_io_projectName: str = Field(..., alias="renku.io/projectName")
    renku_io_renkuVersion: Optional[str] = Field(None, alias="renku.io/renkuVersion")
    renku_io_repository: str = Field(..., alias="renku.io/repository")
    renku_io_resourceClassId: Optional[str] = Field(
        None, alias="renku.io/resourceClassId"
    )
    renku_io_servername: Optional[str] = Field(None, alias="renku.io/servername")
    renku_io_username: Optional[str] = Field(None, alias="renku.io/username")


class State2(Enum):
    running = "running"
    hibernated = "hibernated"


class SessionPatchRequest(BaseAPISpec):
    resource_class_id: Optional[int] = None
    state: Optional[State2] = None


class State3(Enum):
    running = "running"
    starting = "starting"
    stopping = "stopping"
    failed = "failed"
    hibernated = "hibernated"


class SessionStatus(BaseAPISpec):
    message: Optional[str] = None
    state: State3
    will_hibernate_at: Optional[datetime] = None
    will_delete_at: Optional[datetime] = None
    ready_containers: int = Field(..., ge=0)
    total_containers: int = Field(..., ge=0)


class SessionResourcesRequests(BaseAPISpec):
    cpu: Optional[float] = Field(None, description="Fractional CPUs")
    gpu: Optional[int] = Field(None, description="Number of GPUs used")
    memory: Optional[int] = Field(
        None, description="Ammount of RAM for the session, in gigabytes"
    )
    storage: Optional[int] = Field(
        None, description="The size of disk storage for the session, in gigabytes"
    )


class SessionLogsResponse(RootModel[Optional[Dict[str, str]]]):
    root: Optional[Dict[str, str]] = None


class SessionCloudStoragePost(BaseAPISpec):
    configuration: Optional[Dict[str, Any]] = None
    readonly: Optional[bool] = None
    source_path: Optional[str] = None
    target_path: Optional[str] = None
    storage_id: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[0-7][0-9A-HJKMNP-TV-Z]{25}$",
    )


class NotebooksImagesGetParametersQuery(BaseAPISpec):
    image_url: str = Field(..., min_length=1)


class NotebooksLogsServerNameGetParametersQuery(BaseAPISpec):
    max_lines: int = Field(250, ge=0)


class NotebooksServersGetParametersQuery(BaseAPISpec):
    project: Optional[str] = None
    commit_sha: Optional[str] = None
    namespace: Optional[str] = None
    branch: Optional[str] = None


class NotebooksServersServerNameDeleteParametersQuery(BaseAPISpec):
    forced: bool = False


class SessionsSessionIdLogsGetParametersQuery(BaseAPISpec):
    max_lines: int = 250


class SessionsImagesGetParametersQuery(BaseAPISpec):
    image_url: str = Field(..., min_length=1)


class LaunchNotebookRequest(BaseAPISpec):
    project_id: str
    launcher_id: str
    image: Optional[str] = None
    repositories: List[LaunchNotebookRequestRepository] = []
    cloudstorage: List[RCloneStorageRequest] = []
    storage: int = 1
    resource_class_id: Optional[int] = None
    environment_variables: Dict[str, str] = {}
    user_secrets: Optional[UserSecrets] = None


class LaunchNotebookRequestOld(BaseAPISpec):
    branch: str = "master"
    cloudstorage: List[RCloneStorageRequest] = []
    commit_sha: str
    default_url: str = "/lab"
    environment_variables: Dict[str, str] = {}
    image: Optional[str] = None
    lfs_auto_fetch: bool = False
    namespace: str
    notebook: Optional[str] = None
    project: str
    resource_class_id: Optional[int] = None
    serverOptions: Optional[LaunchNotebookRequestServerOptions] = None
    storage: int = 1
    user_secrets: Optional[UserSecrets] = None


class ServerOptionsEndpointResponse(BaseAPISpec):
    cloudstorage: Generated
    defaultUrl: Optional[StringServerOptionsChoice] = None
    lfs_auto_fetch: Optional[BoolServerOptionsChoice] = None


class ServerStatus(BaseAPISpec):
    details: List[ServerStatusDetail]
    message: Optional[str] = None
    readyNumContainers: int = Field(..., ge=0)
    state: State1
    totalNumContainers: int = Field(..., ge=0)
    warnings: Optional[List[ServerStatusWarning]] = None


class SessionResources(BaseAPISpec):
    requests: Optional[SessionResourcesRequests] = None


class NotebookResponse(BaseAPISpec):
    annotations: Optional[FieldUserPodAnnotations] = None
    cloudstorage: Optional[List[LaunchNotebookResponseCloudStorage]] = None
    image: Optional[str] = None
    name: Optional[str] = Field(
        None,
        example="d185e68d-d43-renku-2-b9ac279a4e8a85ac28d08",
        max_length=50,
        min_length=5,
        pattern="^[a-z]([-a-z0-9]*[a-z0-9])?$",
    )
    resources: Optional[UserPodResources] = None
    started: Optional[datetime] = None
    state: Optional[Dict[str, Any]] = None
    status: Optional[ServerStatus] = None
    url: Optional[str] = None


class ServersGetResponse(BaseAPISpec):
    servers: Optional[Dict[str, NotebookResponse]] = None


class SessionPostRequest(BaseAPISpec):
    launcher_id: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[0-7][0-9A-HJKMNP-TV-Z]{25}$",
    )
    disk_storage: int = Field(
        1, description="The size of disk storage for the session, in gigabytes"
    )
    resource_class_id: Optional[int] = None
    cloudstorage: Optional[List[SessionCloudStoragePost]] = None


class SessionResponse(BaseAPISpec):
    image: str
    name: str = Field(
        ...,
        example="d185e68d-d43-renku-2-b9ac279a4e8a85ac28d08",
        max_length=50,
        min_length=5,
        pattern="^[a-z]([-a-z0-9]*[a-z0-9])?$",
    )
    resources: SessionResources
    started: Optional[datetime] = Field(...)
    status: SessionStatus
    url: str
    project_id: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[0-7][0-9A-HJKMNP-TV-Z]{25}$",
    )
    launcher_id: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[0-7][0-9A-HJKMNP-TV-Z]{25}$",
    )
    resource_class_id: int


class SessionListResponse(RootModel[List[SessionResponse]]):
    root: List[SessionResponse]
