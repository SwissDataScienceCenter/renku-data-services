"""Models for Tekton TaskRuns."""

from pydantic import ConfigDict

from renku_data_services.session.cr_base import BaseCRD


class TaskRunStatus(BaseCRD):
    """The status field of a TaskRun."""

    podName: str | None


class TaskRunBase(BaseCRD):
    """Base model for a TaskRun."""

    model_config = ConfigDict(
        extra="allow",
    )
    kind: str = "TaskRun"
    apiVersion: str = "tekton.dev/v1"

    status: TaskRunStatus | None
