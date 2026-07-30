"""Configuration for data connectors and data upload jobs."""

from __future__ import annotations

import json
import os
from collections import namedtuple
from dataclasses import dataclass
from typing import Final

from kubernetes.client import ApiClient, V1Toleration

from renku_data_services.app_config import logging
from renku_data_services.errors import errors
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER, ClusterId

logger = logging.getLogger(__name__)


@dataclass
class DepositConfig:
    """The configuration for running data deposit uploads."""

    image: str
    namespace: str
    renku_url: str
    zenodo_url: str
    envidat: EnvidatConfig
    node_selector: dict[str, str] | None = None
    tolerations: list[V1Toleration] | None = None
    cluster_id: Final[ClusterId] = DEFAULT_K8S_CLUSTER

    @classmethod
    def from_env(cls, renku_url: str) -> DepositConfig:
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
            image=os.environ.get("DATA_DEPOSITS_JOB_IMAGE", "ghcr.io/swissdatasciencecenter/renku-cli"),
            renku_url=renku_url,
            tolerations=tolerations,
            node_selector=node_selector,
            namespace=os.environ["KUBERNETES_NAMESPACE"],
            cluster_id=DEFAULT_K8S_CLUSTER,
            zenodo_url=os.environ.get("ZENODO_URL", "https://zenodo.org").rstrip("/"),
            envidat=EnvidatConfig.from_env(),
        )


@dataclass
class EnvidatConfig:
    """Configuration for envidat data exports and imports."""

    exports_enabled: bool
    url: str
    rclone_image: str
    s3_endpoint: str
    s3_bucket: str
    s3_access_key_id: str
    s3_secret_access_key: str

    @classmethod
    def from_env(cls) -> EnvidatConfig:
        """Generate the config from environment variables."""
        exports_enabled = os.environ.get("ENVIDAT_EXPORTS_ENABLED", "false").lower() == "true"
        output = cls(
            exports_enabled=exports_enabled,
            url=os.environ.get("ENVIDAT_URL", "https://www.envidat.ch").rstrip("/"),
            rclone_image=os.environ.get("ENVIDAT_RCLONE_IMAGE", "rclone/rclone:1"),
            s3_endpoint=os.environ.get("ENVIDAT_S3_ENDPOINT", ""),
            s3_bucket=os.environ.get("ENVIDAT_S3_BUCKET", ""),
            s3_access_key_id=os.environ.get("ENVIDAT_S3_ACCESS_KEY_ID", ""),
            s3_secret_access_key=os.environ.get("ENVIDAT_S3_SECRET_ACCESS_KEY", ""),
        )
        if exports_enabled and any(
            [
                i == ""
                for i in [
                    output.s3_endpoint,
                    output.s3_bucket,
                    output.s3_access_key_id,
                    output.s3_secret_access_key,
                ]
            ]
        ):
            raise errors.ConfigurationError(
                message="Envidat exports are enabled but not all required parameters are provided."
            )
        return output
