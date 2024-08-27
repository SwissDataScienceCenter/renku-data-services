"""Base models for K8s CRD specifications."""

from pydantic import BaseModel


class BaseCRD(BaseModel):
    """Base CRD specification."""

    class Config:
        """Do not exclude unknown properties."""

        extra = "allow"
