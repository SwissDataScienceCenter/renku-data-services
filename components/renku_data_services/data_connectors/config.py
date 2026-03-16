"""Configuration for data connectors and data upload jobs."""

from __future__ import annotations

import json
import os
from collections import namedtuple
from dataclasses import dataclass
from typing import Final

from kubernetes.client import ApiClient, V1Toleration

from renku_data_services.app_config import logging
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER, ClusterId

logger = logging.getLogger(__name__)


@dataclass
class DepositConfig:
    """The configuration for running data deposit uploads."""

    image: str
    namespace: str
    renku_url: str
    zenodo_url: str
    node_selector: dict[str, str] | None = None
    tolerations: list[V1Toleration] | None = None
    cluster_id: Final[ClusterId] = DEFAULT_K8S_CLUSTER

    @classmethod
    def from_env(cls) -> DepositConfig:
        """Create a data deposit configuration from environment variables."""
        # NOTE: The deserialize method from the K8s API client needs the json payload to be in
        # a `data` property on the object passed into the deserializer.
        DeserializerPayload = namedtuple("DeserializerPayload", ["data"])
        deserializer = ApiClient().deserialize
        node_selector: dict[str, str] | None = None
        node_selector_str = os.environ.get("DATA_DEPOSITS_NODE_SELECTOR")
        if node_selector_str:
            try:
                node_selector = json.loads(node_selector_str)
            except (ValueError, TypeError, AttributeError):
                logger.error(
                    "Could not validate DATA_DEPOSITS_NODE_SELECTOR. Will not use node selector for data upload jobs."
                )

        tolerations: list[V1Toleration] | None = None
        tolerations_str = os.environ.get("DATA_DEPOSITS_NODE_TOLERATIONS")
        if tolerations_str:
            try:
                tolerations = deserializer(DeserializerPayload(tolerations_str), "list[V1Toleration]")
                if tolerations is not None:
                    tolerations = [V1Toleration(**t) for t in tolerations]
            except (ValueError, TypeError, AttributeError):
                logger.error(
                    "Could not validate DATA_DEPOSITS_NODE_TOLERATIONS. Will not use tolerations for data upload jobs."
                )
        return cls(
            image=os.environ["DATA_DEPOSITS_JOB_IMAGE"],
            renku_url=os.environ["RENKU_URL"],
            tolerations=tolerations,
            node_selector=node_selector,
            namespace=os.environ["KUBERNETES_NAMESPACE"],
            cluster_id=DEFAULT_K8S_CLUSTER,
            zenodo_url=os.environ.get("ZENODO_URL", "https://zenodo.org").rstrip("/"),
        )
