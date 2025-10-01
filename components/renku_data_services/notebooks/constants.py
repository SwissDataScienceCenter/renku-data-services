"""Constant values used for notebooks."""

from typing import Final

from renku_data_services.k8s.models import GVK

AMALTHEA_SESSION_GVK: Final[GVK] = GVK(group="amalthea.dev", version="v1alpha1", kind="AmaltheaSession")
JUPYTER_SESSION_GVK: Final[GVK] = GVK(group="amalthea.dev", version="v1alpha1", kind="JupyterServer")
