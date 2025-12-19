"""An abstraction over the kr8s kubernetes client and the k8s-watcher."""

from collections.abc import AsyncIterable
from typing import TYPE_CHECKING

import httpx
from kr8s import NotFoundError, ServerError
from kr8s.asyncio.objects import APIObject, Pod

from renku_data_services import errors
from renku_data_services.errors.errors import CannotStartBuildError
from renku_data_services.k8s.constants import ClusterId
from renku_data_services.k8s.models import GVK, K8sObjectFilter, K8sObjectMeta
from renku_data_services.notebooks.api.classes.k8s_client import DEFAULT_K8S_CLUSTER
from renku_data_services.notebooks.util.retries import retry_with_exponential_backoff_async
from renku_data_services.session import crs, models
from renku_data_services.session.constants import (
    BUILD_RUN_GVK,
    DUMMY_TASK_RUN_USER_ID,
    TASK_RUN_GVK,
)
from renku_data_services.session.crs import BuildRun, TaskRun

if TYPE_CHECKING:
    from renku_data_services.k8s.clients import K8sClusterClientsPool


# NOTE The type ignore below is because the kr8s library has no type stubs, they claim pyright better handles type hints
class ShipwrightBuildRunV1Beta1Kr8s(APIObject):
    """Spec for Shipwright BuildRuns used by the k8s client."""

    kind: str = BUILD_RUN_GVK.kind
    version: str = BUILD_RUN_GVK.group_version
    namespaced: bool = True
    plural: str = "buildruns"
    singular: str = "buildrun"
    scalable: bool = False
    endpoint: str = "buildruns"


# NOTE The type ignore below is because the kr8s library has no type stubs, they claim pyright better handles type hints
class TektonTaskRunV1Kr8s(APIObject):
    """Spec for Tekton TaskRuns used by the k8s client."""

    kind: str = TASK_RUN_GVK.kind
    version: str = TASK_RUN_GVK.group_version
    namespaced: bool = True
    plural: str = "taskruns"
    singular: str = "taskrun"
    scalable: bool = False
    endpoint: str = "taskruns"


class ShipwrightClient:
    """The K8s client that combines a base client and a cache.

    No authentication or authorization is performed - this is the responsibility of the caller.
    """

    def __init__(
        self,
        client: "K8sClusterClientsPool",
        namespace: str,
    ) -> None:
        self.client = client
        self.namespace = namespace

    @staticmethod
    def cluster_id() -> ClusterId:
        """Cluster id of the main cluster."""
        return DEFAULT_K8S_CLUSTER

    async def list_build_runs(self, user_id: str) -> AsyncIterable[BuildRun]:
        """Get a list of Shipwright BuildRuns."""
        builds = self.client.list(K8sObjectFilter(namespace=self.namespace, gvk=BUILD_RUN_GVK, user_id=user_id))
        async for build in builds:
            yield BuildRun.model_validate(build.manifest.to_dict())
        return

    async def get_build_run(self, name: str, user_id: str) -> BuildRun | None:
        """Get a Shipwright BuildRun."""
        result = await self.client.get(
            K8sObjectMeta(
                name=name,
                namespace=self.namespace,
                cluster=self.cluster_id(),
                gvk=BUILD_RUN_GVK,
                user_id=user_id,
            )
        )
        if result is None:
            return None

        return BuildRun.model_validate(result.manifest.to_dict())

    async def create_build_run(self, manifest: BuildRun, user_id: str) -> BuildRun:
        """Create a new Shipwright BuildRun."""
        manifest.metadata.namespace = self.namespace
        build_run_name = manifest.metadata.name
        await self.client.create(
            K8sObjectMeta(
                name=build_run_name,
                namespace=self.namespace,
                cluster=self.cluster_id(),
                gvk=BUILD_RUN_GVK,
                user_id=user_id,
            ).with_manifest(manifest=manifest.model_dump(exclude_none=True, mode="json")),
            refresh=False,
        )
        build_resource = await retry_with_exponential_backoff_async(lambda x: x is None)(self.get_build_run)(
            build_run_name, user_id
        )
        if build_resource is None:
            raise CannotStartBuildError(message=f"Cannot create the image build {build_run_name}")
        return build_resource

    async def delete_build_run(self, name: str, user_id: str) -> None:
        """Delete a Shipwright BuildRun."""
        return await self.client.delete(
            K8sObjectMeta(
                name=name,
                namespace=self.namespace,
                cluster=self.cluster_id(),
                gvk=BUILD_RUN_GVK,
                user_id=user_id,
            )
        )

    async def cancel_build_run(self, name: str, user_id: str) -> BuildRun:
        """Cancel a Shipwright BuildRun."""
        build = await self.client.patch(
            K8sObjectMeta(
                name=name,
                namespace=self.namespace,
                cluster=self.cluster_id(),
                gvk=BUILD_RUN_GVK,
                user_id=user_id,
            ),
            patch={"spec": {"state": "BuildRunCanceled"}},
        )
        return BuildRun.model_validate(build.manifest.to_dict())

    async def get_task_run(self, name: str) -> TaskRun | None:
        """Get a Tekton TaskRun.

        Note: since we can't store custom labels on tekton task runs, we use hard-coded fixed user id in the cache db.
        """
        task = await self.client.get(
            K8sObjectMeta(
                name=name,
                namespace=self.namespace,
                cluster=self.cluster_id(),
                gvk=TASK_RUN_GVK,
                user_id=DUMMY_TASK_RUN_USER_ID,
            )
        )
        if task is None:
            return task
        return TaskRun.model_validate(task.manifest.to_dict())

    async def create_image_build(self, params: models.ShipwrightBuildRunParams, user_id: str) -> None:
        """Create a new BuildRun in Shipwright to support a newly created build."""
        metadata = crs.Metadata(name=params.name)
        if params.annotations:
            metadata.annotations = params.annotations
        if params.labels:
            metadata.labels = params.labels

        retention: crs.Retention | None = None
        if params.retention_after_failed or params.retention_after_succeeded:
            retention_after_failed = (
                int(params.retention_after_failed.total_seconds()) if params.retention_after_failed else None
            )
            retention_after_succeeded = (
                int(params.retention_after_succeeded.total_seconds()) if params.retention_after_succeeded else None
            )
            retention = crs.Retention(
                ttlAfterFailed=f"{retention_after_failed}s" if retention_after_failed else None,
                ttlAfterSucceeded=f"{retention_after_succeeded}s" if retention_after_succeeded else None,
            )

        build_run = BuildRun(
            metadata=metadata,
            spec=crs.BuildRunSpec(
                build=crs.Build(
                    spec=crs.BuildSpec(
                        source=crs.GitSource(
                            git=crs.Git(url=params.git_repository, revision=params.git_repository_revision),
                            contextDir=params.context_dir,
                        ),
                        strategy=crs.Strategy(kind="BuildStrategy", name=params.build_strategy_name),
                        paramValues=[
                            crs.ParamValue(name="frontend", value=params.frontend),
                            crs.ParamValue(name="run-image", value=params.run_image),
                            crs.ParamValue(name="builder-image", value=params.builder_image),
                        ],
                        output=crs.BuildOutput(
                            image=params.output_image,
                            pushSecret=params.push_secret_name,
                        ),
                        timeout=f"{params.build_timeout.total_seconds()}s" if params.build_timeout else None,
                        nodeSelector=params.node_selector,
                        tolerations=params.tolerations,
                    )
                ),
                retention=retention,
            ),
        )
        await self.create_build_run(build_run, user_id)

    async def update_image_build_status(self, buildrun_name: str, user_id: str) -> models.ShipwrightBuildStatusUpdate:
        """Update the status of a build by pulling the corresponding BuildRun from Shipwright."""
        k8s_build = await self.get_build_run(name=buildrun_name, user_id=user_id)

        if k8s_build is None:
            return models.ShipwrightBuildStatusUpdate(
                update=models.ShipwrightBuildStatusUpdateContent(status=models.BuildStatus.failed)
            )

        k8s_build_status = k8s_build.status
        completion_time = k8s_build_status.completionTime if k8s_build_status else None

        if k8s_build_status is None or completion_time is None:
            return models.ShipwrightBuildStatusUpdate(update=None)

        conditions = k8s_build_status.conditions
        # NOTE: You can get a condition like this in some cases during autoscaling or for other reasons
        #   message: Not all Steps in the Task have finished executing
        #   reason: Running
        #   status: Unknown
        #   /type: Succeeded
        # or
        #   message: TaskRun Pod exceeded available resources
        #   reason: ExceededNodeResources
        #   status: Unknown
        #   /type: Succeeded
        # In this case we want to keep waiting - the buildrun is still running.
        # A fully successful completion condition looks like this:
        #   reason: Succeeded
        #   status: True
        #   /type: Succeeded
        # See https://shipwright.io/docs/build/buildrun/#understanding-the-state-of-a-buildrun
        # NOTE: In the examples above I put / before the type field because mypy parses that and fails.
        # So I needed something to keep mypy happy. The real name of the field is "type"
        condition = next(filter(lambda c: c.type == "Succeeded", conditions or []), None)

        if condition is not None and condition.status not in ["True", "False"]:
            # The buildrun is still running or pending
            return models.ShipwrightBuildStatusUpdate(update=None)

        buildSpec = k8s_build_status.buildSpec
        output = buildSpec.output if buildSpec else None
        result_image = output.image if output else "unknown"

        source = buildSpec.source if buildSpec else None
        git_obj = source.git if source else None
        result_repository_url = git_obj.url if git_obj else "unknown"

        source_2 = k8s_build_status.source
        git_obj_2 = source_2.git if source_2 else None
        result_repository_git_commit_sha = git_obj_2.commitSha if git_obj_2 else None
        result_repository_git_commit_sha = result_repository_git_commit_sha or "unknown"

        if condition is not None and condition.reason == "Succeeded" and condition.status == "True":
            return models.ShipwrightBuildStatusUpdate(
                update=models.ShipwrightBuildStatusUpdateContent(
                    status=models.BuildStatus.succeeded,
                    completed_at=completion_time,
                    result=models.BuildResult(
                        completed_at=completion_time,
                        image=result_image,
                        repository_url=result_repository_url,
                        repository_git_commit_sha=result_repository_git_commit_sha,
                    ),
                )
            )
        else:
            return models.ShipwrightBuildStatusUpdate(
                update=models.ShipwrightBuildStatusUpdateContent(
                    status=models.BuildStatus.failed,
                    completed_at=completion_time,
                    error_reason=condition.reason if condition is not None else None,
                )
            )

    async def get_image_build_logs(
        self, buildrun_name: str, user_id: str, max_log_lines: int | None = None
    ) -> dict[str, str]:
        """Get the logs from a Shipwright BuildRun."""
        buildrun = await self.get_build_run(name=buildrun_name, user_id=user_id)
        if not buildrun:
            raise errors.MissingResourceError(message=f"Cannot find buildrun {buildrun_name} to retrieve logs.")
        status = buildrun.status
        task_run_name = status.taskRunName if status else None
        if not task_run_name:
            raise errors.MissingResourceError(
                message=f"The buildrun {buildrun_name} has no taskrun to retrieve logs from."
            )
        taskrun = await self.get_task_run(name=task_run_name)
        if not taskrun:
            raise errors.MissingResourceError(
                message=f"Cannot find taskrun from buildrun {buildrun_name} to retrieve logs."
            )
        pod_name = taskrun.status.podName if taskrun.status else None
        if not pod_name:
            raise errors.MissingResourceError(message=f"The buildrun {buildrun_name} has no pod to retrieve logs from.")
        return await self._get_pod_logs(name=pod_name, max_log_lines=max_log_lines)

    async def _get_pod_logs(self, name: str, max_log_lines: int | None = None) -> dict[str, str]:
        """Get the logs of all containers in a given pod."""
        result = await self.client.get(
            K8sObjectMeta(
                name=name, namespace=self.namespace, cluster=self.cluster_id(), gvk=GVK(kind="Pod", version="v1")
            )
        )
        logs: dict[str, str] = {}
        if result is None:
            return logs
        cluster = await self.client.cluster_by_id(result.cluster)

        obj = result.to_api_object(cluster.api)
        result = Pod(resource=obj, namespace=obj.namespace, api=cluster.api)

        containers = [container.name for container in result.spec.containers + result.spec.get("initContainers", [])]
        for container in containers:
            try:
                # NOTE: calling pod.logs without a container name set crashes the library
                clogs: list[str] = [clog async for clog in result.logs(container=container, tail_lines=max_log_lines)]
            except httpx.ResponseNotRead:
                # NOTE: This occurs when the container is still starting, but we try to read its logs
                continue
            except httpx.HTTPStatusError as err:
                # NOTE: This occurs when the container is waiting to start, but we try to read its logs
                if err.response.status_code == 400:
                    continue
                raise
            except NotFoundError as err:
                raise errors.MissingResourceError(message=f"The pod {name} does not exist.") from err
            except ServerError as err:
                if err.response is not None and err.response.status_code == 404:
                    raise errors.MissingResourceError(message=f"The pod {name} does not exist.") from err
                raise
            else:
                logs[container] = "\n".join(clogs)
        return logs
