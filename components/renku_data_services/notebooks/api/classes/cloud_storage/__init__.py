from abc import ABC, abstractmethod, abstractproperty
from typing import Any


class ICloudStorageRequest(ABC):
    @abstractproperty
    def exists(self) -> bool:
        pass

    @abstractproperty
    def mount_folder(self) -> str:
        pass

    @abstractproperty
    def source_folder(self) -> str:
        pass

    @abstractproperty
    def bucket(self) -> str:
        pass

    @abstractmethod
    def get_manifest_patch(
        self,
        base_name: str,
        namespace: str,
        labels: dict[str, str] = {},
        annotations: dict[str, str] = {},
    ) -> list[dict[str, Any]]:
        pass
