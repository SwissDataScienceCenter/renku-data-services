"""Kubernetes Secret wrappers."""

from __future__ import annotations

from base64 import b64encode
from typing import Any, Protocol

from box import Box
from kr8s.objects import Secret
from kubernetes.client import V1Secret

from renku_data_services.errors import ProgrammingError
from renku_data_services.k8s.constants import ClusterId
from renku_data_services.k8s.core import ClusterConnection, K8sClient, sanitizer
from renku_data_services.k8s.models import GVK, K8sObject, K8sObjectMeta, K8sPatches


class K8sSecret(K8sObject):
    """Represents a secret in k8s."""

    def __init__(
        self,
        name: str,
        namespace: str,
        cluster: ClusterId,
        gvk: GVK,
        manifest: Box,
        user_id: str | None = None,
    ) -> None:
        super().__init__(
            name=name,
            namespace=namespace,
            cluster=cluster,
            gvk=gvk,
            manifest=manifest,
            user_id=user_id,
        )

    def __repr__(self) -> str:
        # We hide the manifest to prevent leaking secrets
        return (
            f"{self.__class__.__name__}(name={self.name}, namespace={self.namespace}, cluster={self.cluster}, "
            f"gvk={self.gvk}, user_id={self.user_id})"
        )

    @classmethod
    def from_k8s_object(cls, k8s_object: K8sObject) -> K8sSecret:
        """Convert a k8s object to a K8sSecret object."""
        assert k8s_object.namespace is not None

        return K8sSecret(
            name=k8s_object.name,
            namespace=k8s_object.namespace,
            cluster=k8s_object.cluster,
            gvk=k8s_object.gvk,
            manifest=k8s_object.manifest,
        )

    @classmethod
    def from_v1_secret(cls, secret: V1Secret, cluster: ClusterConnection) -> K8sSecret:
        """Convert a V1Secret object to a K8sSecret object."""
        assert secret.metadata is not None

        return K8sSecret(
            name=secret.metadata.name,
            namespace=cluster.namespace,
            cluster=cluster.id,
            gvk=GVK(version=Secret.version, kind="Secret"),
            manifest=Box(sanitizer(secret)),
        )

    def to_v1_secret(self) -> V1Secret:
        """Convert a K8sSecret to a V1Secret object."""
        return V1Secret(
            metadata=self.manifest.metadata,
            data=self.manifest.get("data", {}),
            string_data=self.manifest.get("stringData", {}),
            type=self.manifest.get("type"),
        )

    @staticmethod
    def __b64encode_values(string_data: dict[str, Any], new_data: dict[str, str]) -> None:
        for k, v in string_data.items():
            if k in new_data:
                raise ProgrammingError(
                    message=f"Patching a secret with both stringData and data and conflicting key {k}."
                )
            new_data[k] = b64encode(str(v).encode("utf-8")).decode("utf-8")

    def to_patch(self) -> K8sPatches:
        """Create a rfc6902 patch that would take an existing secret and patch it to this state."""
        secret_data = self.manifest.get("data") or {}
        string_data = self.manifest.get("stringData")
        if string_data:
            secret_data = secret_data.copy()
            self.__b64encode_values(string_data, secret_data)

        patch = [
            {"op": "replace", "path": "/data", "value": secret_data},
            {"op": "replace", "path": "/type", "value": self.manifest.get("type", "Opaque")},
        ]
        if "metadata" not in self.manifest:
            return patch
        if "labels" in self.manifest.metadata:
            patch.append(
                {"op": "replace", "path": "/metadata/labels", "value": self.manifest.metadata.labels},
            )
        if "annotations" in self.manifest.metadata:
            patch.append(
                {"op": "replace", "path": "/metadata/annotations", "value": self.manifest.metadata.annotations},
            )
        if "ownerReferences" in self.manifest.metadata:
            patch.append(
                {"op": "replace", "path": "/metadata/ownerReferences", "value": self.manifest.metadata.ownerReferences},
            )
        # We never create 'finalizers' nor 'managedFields', so we do not patch them.
        return patch


class SecretClient(Protocol):
    """Methods to manipulate Secret kubernetes resources."""

    async def get_secret(self, secret: K8sObjectMeta) -> K8sSecret | None:
        """Get a secret."""
        ...

    async def create_secret(self, secret: K8sSecret) -> K8sSecret:
        """Create a secret."""
        ...

    async def patch_secret(self, secret: K8sObjectMeta, patch: K8sPatches) -> K8sSecret:
        """Patch an existing secret."""
        ...

    async def delete_secret(self, secret: K8sObjectMeta) -> None:
        """Delete a secret."""
        ...


class K8sSecretClient(SecretClient):
    """A wrapper around a kr8s k8s client, acts on Secrets."""

    def __init__(self, client: K8sClient) -> None:
        self.__client = client

    async def get_secret(self, secret: K8sObjectMeta) -> K8sSecret | None:
        """Get a secret."""
        res = await self.__client.get(secret)
        return K8sSecret.from_k8s_object(res) if res is not None else None

    async def create_secret(self, secret: K8sSecret) -> K8sSecret:
        """Create a secret."""
        return K8sSecret.from_k8s_object(await self.__client.create(secret, False))

    async def patch_secret(self, secret: K8sObjectMeta, patch: K8sPatches) -> K8sSecret:
        """Patch a secret."""
        return K8sSecret.from_k8s_object(await self.__client.patch(secret, patch))

    async def delete_secret(self, secret: K8sObjectMeta) -> None:
        """Delete a secret."""
        await self.__client.delete(secret)


class DummySecretClient(SecretClient):
    """Dummy k8s core API client that does not require a k8s cluster.

    Not suitable for production - to be used only for testing and development.
    """

    async def get_secret(self, secret: K8sObjectMeta) -> K8sSecret | None:
        """Get a secret."""
        raise NotImplementedError()

    async def create_secret(self, secret: K8sSecret) -> K8sSecret:
        """Create a secret."""
        raise NotImplementedError()

    async def patch_secret(self, secret: K8sObjectMeta, patch: K8sPatches) -> K8sSecret:
        """Patch a secret."""
        raise NotImplementedError()

    async def delete_secret(self, secret: K8sObjectMeta) -> None:
        """Delete a secret."""
        raise NotImplementedError()
