# generated by datamodel-codegen:
#   filename:  api.spec.yaml
#   timestamp: 2024-08-06T05:55:34+00:00

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import ConfigDict, Field, RootModel
from renku_data_services.secrets.apispec_base import BaseAPISpec


class Version(BaseAPISpec):
    version: str


class Ulid(RootModel[str]):
    root: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[A-Z0-9]{26}$",
    )


class Error(BaseAPISpec):
    code: int = Field(..., example=1404, gt=0)
    detail: Optional[str] = Field(
        None, example="A more detailed optional message showing what the problem was"
    )
    message: str = Field(..., example="Something went wrong - please try again later")


class ErrorResponse(BaseAPISpec):
    error: Error


class K8sSecret(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str = Field(
        ...,
        description="The name of the k8s secret to create",
        example="john-doe-session-57-secret",
    )
    namespace: str = Field(
        ..., description="The namespace of the k8s secret to create", example="renku"
    )
    secret_ids: List[Ulid] = Field(
        ..., description="The ids of the secrets to include", min_length=1
    )
    owner_references: Optional[List[Dict[str, str]]] = Field(
        None,
        description="The resource in K8s that owns this secret",
        example=[
            {
                "apiVersion": "amalthea.dev/v1alpha1",
                "kind": "JupyterServer",
                "name": "renku-1234",
                "uid": "c9328118-8d32-41b4-b9bd-1437880c95a2",
            }
        ],
    )
