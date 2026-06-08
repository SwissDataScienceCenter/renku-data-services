"""Constant values for k8s."""

from __future__ import annotations

from typing import Final, NewType

from ulid import ULID

ClusterId = NewType("ClusterId", ULID)

DEFAULT_K8S_CLUSTER: Final[ClusterId] = ClusterId(
    ULID.from_str("0RENK1RENK2RENK3RENK4RENK5")
)  # This has to be a valid ULID

DUMMY_TASK_RUN_USER_ID: Final[str] = "DummyTaskRunUser"
"""The user id to use for TaskRuns in the k8s cache.

Note: we can't curently propagate labels to TaskRuns through shipwright, so we just use a dummy user id for all of them.
This might change if shipwright SHIP-0034 gets implemented.
"""

DUMMY_RENKU_APP_USER_ID: Final[str] = "DummyRenkuAppUser"
"""The user id to use for Renku App Knative Services in the k8s cache.

Renku apps are public and shared across users, so they don't fit the per-user cache model. A fixed sentinel
ensures the cache row is shared across all readers instead of being written once per user.
"""
