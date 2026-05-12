from dataclasses import dataclass
from renku_data_services.k8s.client_interfaces import K8sClient


@dataclass
class KnativeClient:
    __k8s_client: K8sClient

    # add wrappers to convert ApiObject to specific CR from crs.py
    # ApiObject to CR
    # CR to ApiObject
    #
    # logs: get pod name from knative config then read logs
    # leave for later
