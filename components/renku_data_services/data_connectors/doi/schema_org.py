"""This is used by envidat and scicat to provide information about their datasets."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from urllib.parse import parse_qs, urlparse

from renku_data_services.data_connectors.doi.models import SchemaOrgDataset
from renku_data_services.errors import errors


class DatasetProvider(StrEnum):
    """The provider for the dataset."""

    envidat = "envidat"


@dataclass
class S3Config:
    """Configuration for a location on S3 storage."""

    rclone_config: dict[str, str]
    bucket: str
    prefix: str

    @property
    def path(self) -> str:
        """Return the path including the bucket name and the prefix."""
        # NOTE: PurePosixPath("/test") / "/subfolder" == /subfolder, so we still have to strip /
        return (PurePosixPath("/") / PurePosixPath(self.bucket) / self.prefix.lstrip("/")).as_posix()


def get_rclone_config(dataset: SchemaOrgDataset, provider: DatasetProvider) -> S3Config:
    """Parse the dataset into an rclone configuration."""
    match provider:
        case DatasetProvider.envidat:
            return __get_rclone_s3_config_envidat(dataset)
        # TODO: Add scicat here
        case _:
            raise errors.ValidationError(message=f"Got an unknown dataset provider {provider}")


def __get_rclone_s3_config_envidat(dataset: SchemaOrgDataset) -> S3Config:
    """Get the S3 rclone configuration and source path from a dataset returned by envidat."""
    # NOTE: The folks from Envidat assure us that the first entity in the list is the one we want
    url = dataset.distribution[0].content_url
    # NOTE: The folks from Envidat assure us that the URL has the following format
    # http://<bucket-name>.<s3 domain>/?prefix=<path to files>
    url_parsed = urlparse(url)
    if not url_parsed.scheme:
        raise errors.ValidationError(message="A scheme like http or https is needed for the S3 url.")
    if not url_parsed.netloc:
        raise errors.ValidationError(message="A hostname is needed for the S3 url.")
    if not url_parsed.query:
        raise errors.ValidationError(message="A query parameter with the path is needed for the S3 url.")
    query_params = parse_qs(url_parsed.query)
    prefix_list = query_params.get("prefix")
    if prefix_list is None or len(prefix_list) == 0:
        raise errors.ValidationError(message="The query paramter in the S3 url should container the 'prefix' key.")
    prefix = prefix_list[0]
    host_split = url_parsed.netloc.split(".")
    if len(host_split) < 2:
        raise errors.ValidationError(
            message="The envidat s3 url is expected to have a host name with at least two parts."
        )
    s3_host = ".".join(host_split[1:])
    bucket = host_split[0].strip("/")
    prefix = "/" + prefix.strip("/")
    return S3Config(
        {
            "type": "s3",
            "provider": "Other",
            "endpoint": f"{url_parsed.scheme}://{s3_host}",
        },
        bucket,
        prefix,
    )
