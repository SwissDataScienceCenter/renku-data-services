"""An abstraction over the kr8s kubernetes client and the k8s-watcher."""

from urllib.parse import urljoin

import httpx
from kr8s import NotFoundError, ServerError
from kr8s.asyncio.objects import APIObject, Pod
from kubernetes.client import ApiClient
from sanic.log import logger

from renku_data_services import errors
from renku_data_services.errors.errors import CannotStartBuildError
from renku_data_services.notebooks.errors.intermittent import CacheError, IntermittentError
from renku_data_services.notebooks.errors.programming import ProgrammingError
from renku_data_services.notebooks.util.retries import retry_with_exponential_backoff_async
from renku_data_services.session import crs, models
from renku_data_services.session.crs import BuildRun, TaskRun


# NOTE The type ignore below is because the kr8s library has no type stubs, they claim pyright better handles type hints
class ShipwrightBuildRunV1Beta1Kr8s(APIObject):
    """Spec for Shipwright BuildRuns used by the k8s client."""

    kind: str = "BuildRun"
    version: str = "shipwright.io/v1beta1"
    namespaced: bool = True
    plural: str = "buildruns"
    singular: str = "buildrun"
    scalable: bool = False
    endpoint: str = "buildruns"


# NOTE The type ignore below is because the kr8s library has no type stubs, they claim pyright better handles type hints
class TektonTaskRunV1Kr8s(APIObject):
    """Spec for Tekton TaskRuns used by the k8s client."""

    kind: str = "TaskRun"
    version: str = "tekton.dev/v1"
    namespaced: bool = True
    plural: str = "taskruns"
    singular: str = "taskrun"
    scalable: bool = False
    endpoint: str = "taskruns"


class _ShipwrightClientBase:
    """Client for managing Shipwright resources in kubernetes.

    NOTE: This does not apply any authentication or authorization on the requests.
    """

    def __init__(self, namespace: str):
        self.namespace = namespace
        self.sanitize = ApiClient().sanitize_for_serialization

    async def create_build_run(self, manifest: BuildRun) -> BuildRun:
        """Create a new Shipwright BuildRun."""
        manifest.metadata.namespace = self.namespace
        build_run = await ShipwrightBuildRunV1Beta1Kr8s(manifest.model_dump(exclude_none=True, mode="json"))
        build_run_name = manifest.metadata.name
        try:
            await build_run.create()
        except ServerError as e:
            logger.exception(f"Cannot create the image build {build_run_name} because of {e}")
            raise CannotStartBuildError(message=f"Cannot create the image build {build_run_name}")
        await build_run.refresh()
        build_resource = await retry_with_exponential_backoff_async(lambda x: x is None)(self.get_build_run)(
            build_run_name
        )
        if build_resource is None:
            raise CannotStartBuildError(message=f"Cannot create the image build {build_run_name}")
        return build_resource

    async def get_build_run(self, name: str) -> BuildRun | None:
        """Get a Shipwright BuildRun."""
        try:
            build = await ShipwrightBuildRunV1Beta1Kr8s.get(name=name, namespace=self.namespace)
        except NotFoundError:
            return None
        except ServerError as e:
            if not e.response or e.response.status_code not in [400, 404]:
                logger.exception(f"Cannot get the build {name} because of {e}")
                raise IntermittentError(f"Cannot get build {name} from the k8s API.")
            return None
        return BuildRun.model_validate(build.to_dict())

    async def list_build_runs(self, label_selector: str | None = None) -> list[BuildRun]:
        """Get a list of Shipwright BuildRuns."""
        try:
            builds = await ShipwrightBuildRunV1Beta1Kr8s.list(namespace=self.namespace, label_selector=label_selector)
        except ServerError as e:
            if not e.response or e.response.status_code not in [400, 404]:
                logger.exception(f"Cannot list builds because of {e}")
                raise IntermittentError("Cannot list builds")
            return []
        output = [BuildRun.model_validate(b.to_dict()) for b in builds]
        return output

    async def delete_build_run(self, name: str) -> None:
        """Delete a Shipwright BuildRun."""
        build = await ShipwrightBuildRunV1Beta1Kr8s(dict(metadata=dict(name=name, namespace=self.namespace)))
        try:
            await build.delete(propagation_policy="Foreground")
        except ServerError as e:
            logger.exception(f"Cannot delete build {name} because of {e}")
        return None

    async def get_task_run(self, name: str) -> TaskRun | None:
        """Get a Tekton TaskRun."""
        try:
            task = await TektonTaskRunV1Kr8s.get(name=name, namespace=self.namespace)
        except NotFoundError:
            return None
        except ServerError as e:
            if not e.response or e.response.status_code not in [400, 404]:
                logger.exception(f"Cannot get the build {name} because of {e}")
                raise IntermittentError(f"Cannot get build {name} from the k8s API.")
            return None
        return TaskRun.model_validate(task.to_dict())

    async def get_pod_logs(self, name: str, max_log_lines: int | None = None) -> dict[str, str]:
        """Get the logs of all containers in a given pod."""
        pod = await Pod.get(name=name, namespace=self.namespace)
        logs: dict[str, str] = {}
        containers = [container.name for container in pod.spec.containers + pod.spec.get("initContainers", [])]
        for container in containers:
            try:
                # NOTE: calling pod.logs without a container name set crashes the library
                clogs: list[str] = [clog async for clog in pod.logs(container=container, tail_lines=max_log_lines)]
            except httpx.ResponseNotRead:
                # NOTE: This occurs when the container is still starting but we try to read its logs
                continue
            except NotFoundError:
                raise errors.MissingResourceError(message=f"The pod {name} does not exist.")
            except ServerError as err:
                if err.response is not None and err.response.status_code == 404:
                    raise errors.MissingResourceError(message=f"The pod {name} does not exist.")
                raise
            else:
                logs[container] = "\n".join(clogs)
        return logs


class _ShipwrightCache:
    """Utility class for calling the Shipwright k8s cache."""

    def __init__(self, url: str):
        self.url = url
        self.client = httpx.AsyncClient(timeout=10)

    async def list_build_runs(self) -> list[BuildRun]:
        """Get a list of Shipwright BuildRuns."""
        url = urljoin(self.url, "/buildruns")
        try:
            res = await self.client.get(url, timeout=10)
        except httpx.RequestError as err:
            logger.warning(f"Shipwright k8s cache at {url} cannot be reached: {err}")
            raise CacheError("The shipwright k8s cache is not available")
        if res.status_code != 200:
            logger.warning(
                f"Listing build runs at {url} from "
                f"shipwright k8s cache failed with status code: {res.status_code} "
                f"and body: {res.text}"
            )
            raise CacheError(f"The K8s Cache produced an unexpected status code: {res.status_code}")

        return [BuildRun.model_validate(server) for server in res.json()]

    async def get_build_run(self, name: str) -> BuildRun | None:
        """Get a Shipwright BuildRun."""
        url = urljoin(self.url, f"/buildruns/{name}")
        try:
            res = await self.client.get(url, timeout=10)
        except httpx.RequestError as err:
            logger.warning(f"Shipwright k8s cache at {url} cannot be reached: {err}")
            raise CacheError("The shipwright k8s cache is not available")
        if res.status_code != 200:
            logger.warning(
                f"Reading build run at {url} from "
                f"shipwright k8s cache failed with status code: {res.status_code} "
                f"and body: {res.text}"
            )
            raise CacheError(f"The K8s Cache produced an unexpected status code: {res.status_code}")
        output = res.json()
        if len(output) == 0:
            return None
        if len(output) > 1:
            raise ProgrammingError(
                message=f"Expected to find 1 build run when getting run {name}, found {len(output)}."
            )
        return BuildRun.model_validate(output[0])

    async def get_task_run(self, name: str) -> TaskRun | None:
        """Get a Tekton TaskRun."""
        url = urljoin(self.url, f"/taskruns/{name}")
        try:
            res = await self.client.get(url, timeout=10)
        except httpx.RequestError as err:
            logger.warning(f"Tekton k8s cache at {url} cannot be reached: {err}")
            raise CacheError("The tekton k8s cache is not available")
        if res.status_code != 200:
            logger.warning(
                f"Reading task run at {url} from "
                f"tekton k8s cache failed with status code: {res.status_code} "
                f"and body: {res.text}"
            )
            raise CacheError(f"The K8s Cache produced an unexpected status code: {res.status_code}")
        output = res.json()
        if len(output) == 0:
            return None
        if len(output) > 1:
            raise ProgrammingError(message=f"Expected to find 1 task run when getting run {name}, found {len(output)}.")
        return TaskRun.model_validate(output[0])


class ShipwrightClient:
    """The K8s client that combines a base client and a cache.

    No authentication or authorization is performed - this is the responsibility of the caller.
    """

    def __init__(
        self,
        namespace: str,
        cache_url: str,
        # NOTE: If cache skipping is enabled then when the cache fails a large number of
        # buildruns can overload the k8s API by submitting a lot of calls directly.
        skip_cache_if_unavailable: bool = False,
    ) -> None:
        self.cache = _ShipwrightCache(url=cache_url)
        self.base_client = _ShipwrightClientBase(namespace=namespace)
        self.skip_cache_if_unavailable = skip_cache_if_unavailable

    async def list_build_runs(self) -> list[BuildRun]:
        """Get a list of Shipwright BuildRuns."""
        try:
            return await self.cache.list_build_runs()
        except CacheError:
            if self.skip_cache_if_unavailable:
                logger.warning("Skipping the cache to list BuildRuns")
                return await self.base_client.list_build_runs()
            else:
                raise

    async def get_build_run(self, name: str) -> BuildRun | None:
        """Get a Shipwright BuildRun."""
        try:
            return await self.cache.get_build_run(name)
        except CacheError:
            if self.skip_cache_if_unavailable:
                return await self.base_client.get_build_run(name)
            else:
                raise

    async def create_build_run(self, manifest: BuildRun) -> BuildRun:
        """Create a new Shipwright BuildRun."""
        return await self.base_client.create_build_run(manifest)

    async def delete_build_run(self, name: str) -> None:
        """Delete a Shipwright BuildRun."""
        return await self.base_client.delete_build_run(name)

    async def get_task_run(self, name: str) -> TaskRun | None:
        """Get a Tekton TaskRun."""
        try:
            return await self.cache.get_task_run(name)
        except CacheError:
            if self.skip_cache_if_unavailable:
                return await self.base_client.get_task_run(name)
            else:
                raise

    async def create_image_build(self, params: models.ShipwrightBuildRunParams) -> None:
        """Create a new BuildRun in Shipwright to support a newly created build."""
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
            metadata=crs.Metadata(name=params.name),
            spec=crs.BuildRunSpec(
                build=crs.Build(
                    spec=crs.BuildSpec(
                        source=crs.GitSource(git=crs.Git(url=params.git_repository)),
                        strategy=crs.Strategy(kind="BuildStrategy", name=params.build_strategy_name),
                        paramValues=[crs.ParamValue(name="run-image", value=params.run_image)],
                        output=crs.BuildOutput(
                            image=params.output_image,
                            pushSecret=params.push_secret_name,
                        ),
                        timeout=f"{params.build_timeout.total_seconds()}s" if params.build_timeout else None,
                        nodeSelector=params.node_selector,
                        tolerations=[],
                    )
                ),
                retention=retention,
            ),
        )
        await self.create_build_run(build_run)

    async def update_image_build_status(self, buildrun_name: str) -> models.ShipwrightBuildStatusUpdate:
        """Update the status of a build by pulling the corresponding BuildRun from Shipwright."""
        k8s_build = await self.get_build_run(name=buildrun_name)

        if k8s_build is None:
            return models.ShipwrightBuildStatusUpdate(
                update=models.ShipwrightBuildStatusUpdateContent(status=models.BuildStatus.failed)
            )

        k8s_build_status = k8s_build.status
        completion_time = k8s_build_status.completionTime if k8s_build_status else None

        if k8s_build_status is None or completion_time is None:
            return models.ShipwrightBuildStatusUpdate(update=None)

        conditions = k8s_build_status.conditions
        condition = next(filter(lambda c: c.type == "Succeeded", conditions or []), None)

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

        if condition is not None and condition.status == "True":
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
                )
            )

    async def cancel_image_build(self, buildrun_name: str) -> None:
        """Cancel a build by deleting the corresponding BuildRun from Shipwright."""
        # TODO: use proper cancellation, see: https://shipwright.io/docs/build/buildrun/#canceling-a-buildrun
        await self.delete_build_run(name=buildrun_name)

    async def get_image_build_logs(self, buildrun_name: str, max_log_lines: int | None = None) -> dict[str, str]:
        """Get the logs from a Shipwright BuildRun."""
        buildrun = await self.get_build_run(name=buildrun_name)
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
        return await self.base_client.get_pod_logs(name=pod_name, max_log_lines=max_log_lines)
