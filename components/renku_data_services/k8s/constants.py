"""Constant values for k8s."""

from typing import Final

from renku_data_services.k8s.models import ClusterId

DEFAULT_K8S_CLUSTER: Final[ClusterId] = ClusterId("renkulab")
