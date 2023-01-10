from abc import ABC, abstractmethod, abstractproperty
from typing import Any, Dict


class ICloudStorageRequest(ABC):
    @abstractproperty
    def exists(self) -> bool:
        pass

    @abstractproperty
    def mount_folder(self) -> str:
        pass

    @abstractproperty
    def bucket(self) -> str:
        pass

    @abstractmethod
    def get_manifest_patch(
        self,
        base_name: str,
        namespace: str,
        labels: Dict[str, str] = {},
        annotations: Dict[str, str] = {},
    ) -> Dict[str, Any]:
        pass
