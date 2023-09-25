"""Models for cloud storage."""

from collections.abc import MutableMapping
from typing import Any
from urllib.parse import ParseResult, urlparse

from pydantic import BaseModel, Field, PrivateAttr, model_serializer, model_validator

from renku_data_services import errors
from renku_data_services.storage_schemas.core import RCloneValidator


class RCloneConfig(BaseModel, MutableMapping):
    """Class for RClone configuration that is valid."""

    config: dict[str, Any] = Field(exclude=True)

    private: bool = Field(exclude=True)
    _validator: RCloneValidator = PrivateAttr(default=RCloneValidator())

    @model_validator(mode="after")
    def check_rclone_schema(self) -> "RCloneConfig":
        """Validate that the reclone config is valid."""
        self._validator.validate(self.config, private=self.private)
        return self

    @model_serializer
    def serialize_model(self) -> dict[str, Any]:
        """Serialize model by returning contained dict."""
        return self.config

    def __len__(self):
        return len(self.config)

    def __getitem__(self, k):
        return self.config[k]

    def __setitem__(self, key, value):
        self.config[key] = value
        self._validator.validate(self.config, private=self.private)

    def __delitem__(self, key):
        del self.config[key]
        self._validator.validate(self.config, private=self.private)

    def __iter__(self):
        return iter(self.config)


class CloudStorage(BaseModel):
    """Cloud Storage model."""

    project_id: str = Field(pattern=r"^\d+$")
    name: str = Field(min_length=3)
    storage_type: str = Field(pattern=r"^[a-z0-9]+$")
    configuration: RCloneConfig
    private: bool = Field(default=False)

    storage_id: str | None = Field(default=None)

    source_path: str = Field(min_length=1)
    """Path inside the cloud storage.

    Note: Since rclone itself doesn't really know about buckets/containers (they're not in the schema),
    bucket/container/etc. has to be the first part of source path.
    """

    target_path: str = Field(min_length=1)
    """Path inside the target repository to mouhnt/clone data to."""

    @classmethod
    def from_dict(cls, data: dict) -> "CloudStorage":
        """Create the model from a plain dictionary."""

        if "project_id" not in data:
            raise errors.ValidationError(message="'project_id' not set")
        if "configuration" not in data:
            raise errors.ValidationError(message="'configuration' not set")

        if "source_path" not in data:
            raise errors.ValidationError(message="project_id not set")

        if "target_path" not in data:
            raise errors.ValidationError(message="project_id not set")

        if "type" not in data["configuration"]:
            raise errors.ValidationError(message="'type' not set in 'configuration'")

        private = data.get("private", False)
        return cls(
            project_id=data["project_id"],
            storage_id=data.get("storage_id"),
            name=data["name"],
            configuration=RCloneConfig(config=data["configuration"], private=private),
            storage_type=data["configuration"]["type"],
            source_path=data["source_path"],
            target_path=data["target_path"],
            private=private,
        )

    @classmethod
    def from_url(cls, storage_url: str, name: str, private: bool, project_id: str, target_path: str) -> "CloudStorage":
        """Get Cloud Storage/rclone config from a storage URL.

        Example:
            Supported URLs are:
            - s3://s3.<region>.amazonaws.com/<bucket>/<path>
            - s3://<bucket>.s3.<region>.amazonaws.com/<path>
            - s3://bucket/
            - http(s)://<endpoint>/<bucket>/<path>
            - (azure|az)://<account>.dfs.core.windows.net/<container>/<path>
            - (azure|az)://<account>.blob.core.windows.net/<container>/<path>
            - (azure|az)://<container>/<path>
        """
        parsed_url = urlparse(storage_url)

        if parsed_url.scheme is None:
            raise errors.ValidationError(message="Couldn't parse scheme of 'storage_url'")

        match parsed_url.scheme:
            case "s3":
                return CloudStorage.from_s3_url(parsed_url, project_id, name, private, target_path)
            case "azure" | "az":
                return CloudStorage.from_azure_url(parsed_url, project_id, name, private, target_path)
            case "http" | "https":
                return CloudStorage._from_ambiguous_url(parsed_url, project_id, name, private, target_path)
            case _:
                raise errors.ValidationError(message=f"Scheme '{parsed_url.scheme}' is not supported.")

    @classmethod
    def from_s3_url(
        cls, storage_url: ParseResult, project_id: str, name: str, private: bool, target_path: str
    ) -> "CloudStorage":
        """Get Cloud storage from an S3 URL.

        Example:
            Supported URLs are:
            - s3://s3.<region>.amazonaws.com/<bucket>/<path>
            - s3://<bucket>.s3.<region>.amazonaws.com/<path>
            - s3://bucket/
            - https://<endpoint>/<bucket>/<path>
        """

        if storage_url.hostname is None:
            raise errors.ValidationError(message="Storage URL must contain a host")

        configuration = {"type": "s3"}
        source_path = storage_url.path.lstrip("/")

        if storage_url.scheme == "s3":
            configuration["provider"] = "AWS"
            match storage_url.hostname.split(".", 4):
                case ["s3", region, "amazonaws", "com"]:
                    configuration["region"] = region
                case [bucket, "s3", region, "amazonaws", "com"]:
                    configuration["region"] = region
                    source_path = f"{bucket}{storage_url.path}"
                case _:
                    # URL like 's3://giab/' where the bucket is the
                    source_path = f"{storage_url.hostname}/{source_path}" if source_path else storage_url.hostname
        else:
            configuration["endpoint"] = storage_url.netloc

        return cls(
            project_id=project_id,
            name=name,
            storage_type="s3",
            configuration=RCloneConfig(config=configuration, private=private),
            source_path=source_path,
            target_path=target_path,
            private=private,
        )

    @classmethod
    def from_azure_url(
        cls, storage_url: ParseResult, project_id: str, name: str, private: bool, target_path: str
    ) -> "CloudStorage":
        """Get Cloud storage from an Azure URL.

        Example:
            Supported URLs are:
            - (azure|az)://<account>.dfs.core.windows.net/<container>/<path>
            - (azure|az)://<account>.blob.core.windows.net/<container>/<path>
            - (azure|az)://<container>/<path>
        """
        if storage_url.hostname is None:
            raise errors.ValidationError(message="Storage URL must contain a host")

        configuration = {"type": "azureblob"}
        source_path = storage_url.path.lstrip("/")

        match storage_url.hostname.split(".", 5):
            case [account, "dfs", "core", "windows", "net"] | [account, "blob", "core", "windows", "net"]:
                configuration["account"] = account
            case _:
                if "." in storage_url.hostname:
                    raise errors.ValidationError(message="Host cannot contain dots unless it's a core.windows.net URL")

                source_path = f"{storage_url.hostname}{storage_url.path}"
        return cls(
            project_id=project_id,
            name=name,
            storage_type="azureblob",
            configuration=RCloneConfig(config=configuration, private=private),
            source_path=source_path,
            target_path=target_path,
            private=private,
        )

    @classmethod
    def _from_ambiguous_url(
        cls, storage_url: ParseResult, project_id: str, name: str, private: bool, target_path: str
    ) -> "CloudStorage":
        """Get cloud storage from an ambiguous storage url."""
        if storage_url.hostname is None:
            raise errors.ValidationError(message="Storage URL must contain a host")

        if storage_url.hostname.endswith(".windows.net"):
            return CloudStorage.from_azure_url(storage_url, project_id, name, private, target_path)

        # default to S3 for unknown URLs, since these are way more common
        return CloudStorage.from_s3_url(storage_url, project_id, name, private, target_path)
