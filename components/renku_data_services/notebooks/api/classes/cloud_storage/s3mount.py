from typing import Any, Dict, Optional
from urllib.parse import urlparse

import boto3
from botocore import UNSIGNED
from botocore.client import Config
from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError

from ....config import config
from . import ICloudStorageRequest


class S3Request(ICloudStorageRequest):
    def __init__(
        self,
        bucket,
        mount_folder,
        endpoint,
        access_key=None,
        secret_key=None,
        read_only=False,
    ):
        self.access_key = access_key if access_key != "" else None
        self.secret_key = secret_key if secret_key != "" else None
        self.endpoint = endpoint
        self._bucket = bucket
        self.read_only = read_only
        self.public = False
        if self.access_key is None and self.secret_key is None:
            self.public = True
        if self.public:
            self.client = boto3.session.Session().client(
                service_name="s3",
                endpoint_url=self.endpoint,
                config=Config(signature_version=UNSIGNED),
            )
        else:
            self.client = boto3.session.Session().client(
                service_name="s3",
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                endpoint_url=self.endpoint,
            )
        self._mount_folder = str(mount_folder).rstrip("/")
        self.__head_bucket = {}

    def get_manifest_patch(
        self, base_name: str, namespace: str, labels={}, annotations={}
    ) -> Dict[str, Any]:
        secret_name = f"{base_name}-secret"
        # prepare datashim dataset spec
        s3mount_spec = {
            "local": {
                "type": "COS",
                "endpoint": self.region_specific_endpoint
                if self.region_specific_endpoint
                else self.endpoint,
                "bucket": self.bucket,
                "readonly": "true" if self.read_only else "false",
            }
        }
        if not self.public:
            s3mount_spec["local"]["secret-name"] = f"{secret_name}"
            s3mount_spec["local"]["secret-namespace"] = namespace
        else:
            s3mount_spec["local"]["accessKeyID"] = ""
            s3mount_spec["local"]["secretAccessKey"] = "secret"
        patch = {
            "type": "application/json-patch+json",
            "patch": [
                # add whole datashim dataset spec
                {
                    "op": "add",
                    "path": f"/{base_name}",
                    "value": {
                        "apiVersion": "com.ie.ibm.hpsys/v1alpha1",
                        "kind": "Dataset",
                        "metadata": {
                            "name": base_name,
                            "namespace": namespace,
                            "labels": labels,
                            "annotations": {
                                **annotations,
                                config.session_get_endpoint_annotations.renku_annotation_prefix
                                + "mount_folder": self.mount_folder,
                            },
                        },
                        "spec": s3mount_spec,
                    },
                },
                # mount dataset into user session
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/0/volumeMounts/-",
                    "value": {
                        "mountPath": self.mount_folder + "/" + self.bucket,
                        "name": base_name,
                    },
                },
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/volumes/-",
                    "value": {
                        "name": base_name,
                        "persistentVolumeClaim": {"claimName": base_name},
                    },
                },
            ],
        }
        # add secret for storing access keys for s3
        if not self.public:
            patch["patch"].append(
                {
                    "op": "add",
                    "path": f"/{secret_name}",
                    "value": {
                        "apiVersion": "v1",
                        "kind": "Secret",
                        "metadata": {
                            "name": secret_name,
                            "namespace": namespace,
                            "labels": labels,
                            "annotations": annotations,
                        },
                        "stringData": {
                            "accessKeyID": self.access_key,
                            "secretAccessKey": self.secret_key,
                        },
                    },
                },
            )
        return patch

    @property
    def head_bucket(self):
        """Used to determine the AWS location for the bucket and if the bucket
        exists or not."""
        if self.__head_bucket != {}:
            return self.__head_bucket
        try:
            self.__head_bucket = self.client.head_bucket(Bucket=self.bucket)
        except (ClientError, EndpointConnectionError, NoCredentialsError, ValueError):
            self.__head_bucket = None
        return self.__head_bucket

    @property
    def exists(self) -> bool:
        if self.head_bucket is None:
            return False
        amz_bucket_region = (
            self.head_bucket.get("ResponseMetadata", {})
            .get("HTTPHeaders", {})
            .get("x-amz-bucket-region")
        )
        parsed_endpoint = urlparse(self.endpoint)
        if (
            amz_bucket_region
            and parsed_endpoint.netloc.endswith("amazonaws.com")
            and parsed_endpoint.netloc != "s3.amazonaws.com"
            and amz_bucket_region not in self.endpoint
        ):
            return False
        return True

    @property
    def bucket(self) -> str:
        return self._bucket

    @property
    def region_specific_endpoint(self) -> Optional[str]:
        """Get the region specific endpoint if the bucket exists and the general
        non-region-specific URL for AWS is used."""
        if not self.head_bucket:
            return None
        # INFO: If the region is not the default (us-east-1) and it is not specified explicitly in
        # the endpoint then datashim has trouble mounting the bucket even though boto can find it.
        amz_bucket_region = (
            self.head_bucket.get("ResponseMetadata", {})
            .get("HTTPHeaders", {})
            .get("x-amz-bucket-region")
        )
        if amz_bucket_region and urlparse(self.endpoint).netloc == "s3.amazonaws.com":
            return f"https://s3.{amz_bucket_region}.amazonaws.com"

    @property
    def mount_folder(self):
        return self._mount_folder
