"""Models for cloud storage."""

from __future__ import annotations

from collections.abc import Generator, MutableMapping
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import ParseResult, urlparse

from pydantic import BaseModel, Field, PrivateAttr, model_serializer, model_validator

from renku_data_services import errors
from renku_data_services.storage.rclone import RCloneValidator


class RCloneConfig(BaseModel, MutableMapping):
    """Class for RClone configuration that is valid."""

    config: dict[str, Any] = Field(exclude=True)

    _validator: RCloneValidator = PrivateAttr(default=RCloneValidator())

    @model_validator(mode="after")
    def check_rclone_schema(self) -> RCloneConfig:
        """Validate that the reclone config is valid."""
        self._validator.validate(self.config)
        return self

    @model_serializer
    def serialize_model(self) -> dict[str, Any]:
        """Serialize model by returning contained dict."""
        return self.config

    def __len__(self) -> int:
        return len(self.config)

    def __getitem__(self, k: str) -> Any:
        return self.config[k]

    def __setitem__(self, key: str, value: Any) -> None:
        self.config[key] = value
        self._validator.validate(self.config)

    def __delitem__(self, key: str) -> None:
        del self.config[key]
        self._validator.validate(self.config)

    def __iter__(self) -> Generator[str, None, None]:  # type: ignore[override]
        """Iterate method.

        Needed for pydantic to properly serialize the object.
        """
        yield from self.config.keys()


def storage_url_parser(storage_url: str) -> tuple[RCloneConfig, PurePosixPath]:
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

    def from_s3_url(storage_url: ParseResult) -> tuple[RCloneConfig, PurePosixPath]:
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

        return RCloneConfig(config=configuration), PurePosixPath(source_path)

    def from_azure_url(storage_url: ParseResult) -> tuple[RCloneConfig, PurePosixPath]:
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
        return RCloneConfig(config=configuration), PurePosixPath(source_path)

    def _from_ambiguous_url(storage_url: ParseResult) -> tuple[RCloneConfig, PurePosixPath]:
        """Get cloud storage from an ambiguous storage url."""
        if storage_url.hostname is None:
            raise errors.ValidationError(message="Storage URL must contain a host")

        if storage_url.hostname.endswith(".windows.net"):
            return from_azure_url(storage_url)

        # default to S3 for unknown URLs, since these are way more common
        return from_s3_url(storage_url)

    parsed_url = urlparse(storage_url)

    if parsed_url.scheme is None:
        raise errors.ValidationError(message="Couldn't parse scheme of 'storage_url'")

    match parsed_url.scheme:
        case "s3":
            return from_s3_url(parsed_url)
        case "azure" | "az":
            return from_azure_url(parsed_url)
        case "http" | "https":
            return _from_ambiguous_url(parsed_url)
        case _:
            raise errors.ValidationError(message=f"Scheme '{parsed_url.scheme}' is not supported.")
