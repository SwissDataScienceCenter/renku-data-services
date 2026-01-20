import pytest

from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.resource_usage.core import ResourceRequestsFetch, ResourceRequestsRepo, ResourcesRequestRecorder
from renku_data_services.resource_usage.model import CpuUsage


def test_cpu_usage() -> None:
    cu1 = CpuUsage.from_string("189963n") or CpuUsage.zero()
    cu2 = CpuUsage.from_string("889963n") or CpuUsage.zero()
    print(cu1 + cu2)


@pytest.mark.asyncio
async def test_play(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")

    #    print(app_manager_instance.k8s_client.__clients)

    rcd = ResourceRequestsFetch(app_manager_instance.k8s_client)
    repo = ResourceRequestsRepo(app_manager_instance.config.db.async_session_maker)
    recorder = ResourcesRequestRecorder(repo, rcd)
    await recorder.record_resource_requests("renku")

    all = repo.find_all()
    async for e in all:
        print(e)
