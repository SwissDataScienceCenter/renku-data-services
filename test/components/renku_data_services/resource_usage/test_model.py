import pytest
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.resource_usage.core import ResourceRequestsFetch
from renku_data_services.resource_usage.model import CpuUsage


def test_cpu_usage() -> None:
    cu1 = CpuUsage.from_string("189963n") or CpuUsage.zero()
    cu2 = CpuUsage.from_string("889963n") or CpuUsage.zero()
    print(cu1 + cu2)


@pytest.mark.asyncio
async def test_play(app_manager_instance: DependencyManager) -> None:

    rcd = ResourceRequestsFetch(app_manager_instance.k8s_client)
    result = await rcd.get_resources_requests()
    print(result)
    # data = rcd.test()
    # print()
    # for _,e in data.items():
    #     print(e)
