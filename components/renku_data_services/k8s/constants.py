"""Constant values for k8s."""

from typing import Final

from renku_data_services.k8s.models import ClusterId

DEFAULT_K8S_CLUSTER: Final[ClusterId] = ClusterId("0RENK1RENK2RENK3RENK4RENK5")  # This has to be a valid ULID

DUMMY_TASK_RUN_USER_ID: Final[str] = "DummyTaskRunUser"
"""The user id to use for TaskRuns in the k8s cache.

Note: we can't curently propagate labels to TaskRuns through shipwright, so we just use a dummy user id for all of them.
This might change if shipwright SHIP-0034 gets implemented.
"""
