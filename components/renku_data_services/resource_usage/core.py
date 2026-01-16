import datetime
from renku_data_services.k8s.client_interfaces import K8sClient
from renku_data_services.k8s.constants import ClusterId
from renku_data_services.k8s.models import GVK, K8sObjectFilter, K8sObjectMeta

from kubernetes import client, config
from renku_data_services.resource_usage.model import CpuUsage, MemoryUsage, RequestData, ResourcesRequest


class ResourceRequestsFetch:
    """Get resource request data."""

    def __init__(self, k8s_client: K8sClient) -> None:
        config.load_config()
        self._client = k8s_client
        self._v1 = client.CoreV1Api()

    def _get_name_label(self, pod) -> str | None:
        return pod.metadata.labels.get("app.kubernetes.io/name")

    async def get_resources_requests(self) -> dict[str, ResourcesRequest]:
        """Return the resources requests of all sessions."""
        async for obj in self._client.list(K8sObjectFilter(gvk=GVK(kind="pod", version="v1"))):
            print(obj.manifest)

        return {}

    def test(self) -> dict[str, ResourcesRequest]:
        all_pods = self._v1.list_namespaced_pod(namespace="renku")
        now = datetime.datetime.now()
        result = {}
        for pod in all_pods.items:
            if self._get_name_label(pod) != "AmaltheaSession":
                continue

            pn = pod.metadata.name
            pns = pod.metadata.namespace
            for container in pod.spec.containers:
                # .resources.requests is a dictionary (e.g., {'cpu': '100m', 'memory': '128Mi'})
                requests = container.resources.requests or {}
                lims = container.resources.limits or {}

                cpu_req = CpuUsage.from_string(requests.get("cpu", "0"))
                mem_req = MemoryUsage.from_string(requests.get("memory", "0"))
                gpu_req = CpuUsage.from_string(lims.get("nvidia.com/gpu") or requests.get("nvidia.com/gpu", "0"))

                rdat = RequestData(
                    cpu=cpu_req or CpuUsage.zero(), memory=mem_req or MemoryUsage.zero(), gpu=gpu_req or CpuUsage.zero()
                )
                rreq = ResourcesRequest(namespace=pns, pod_name=pn, capture_date=now, data=rdat)
                nreq = rreq.add(result.get(rreq.id) or rreq.to_zero())
                result.update({nreq.id: nreq})

        return result
