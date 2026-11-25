"""Base models for K8s CRD specifications."""

from pydantic import BaseModel, ConfigDict


class BaseCRD(BaseModel):
    """Base CRD specification."""

    model_config = ConfigDict(extra="allow")
