"""An abstraction over the kr8s kubernetes client and the k8s-watcher."""

from urllib.parse import urljoin

import httpx
from kr8s import NotFoundError, ServerError
from kr8s.asyncio.objects import APIObject
from kubernetes.client import ApiClient
from sanic.log import logger

from renku_data_services.errors.errors import CannotStartBuildError
from renku_data_services.notebooks.errors.intermittent import CacheError, IntermittentError
from renku_data_services.notebooks.errors.programming import ProgrammingError
from renku_data_services.notebooks.util.retries import retry_with_exponential_backoff_async
from renku_data_services.session import crs, models
from renku_data_services.session.crs import BuildRun


# NOTE The type ignore below is because the kr8s library has no type stubs, they claim pyright better handles type hints
class ShipwrightBuildRunV1Beta1Kr8s(APIObject):
    """Spec for ShipWright BuildRuns used by the k8s client."""

    kind: str = "BuildRun"
    version: str = "shipwright.io/v1beta1"
    namespaced: bool = True
    plural: str = "buildruns"
    singular: str = "buildrun"
    scalable: bool = False
    endpoint: str = "buildruns"


class _ShipwrightClientBase:
    """Client for managing ShipWright resources in kubernetes.

    NOTE: This does not apply any authentication or authorization on the requests.
    """

    def __init__(self, namespace: str):
        self.namespace = namespace
        self.sanitize = ApiClient().sanitize_for_serialization

    async def create_build_run(self, manifest: BuildRun) -> BuildRun:
        """Create a new ShipWright BuildRun."""
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
        """Get a ShipWright BuildRun."""
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
        """Get a list of ShipWright BuildRuns."""
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
        """Delete a ShipWright BuildRun."""
        build = await ShipwrightBuildRunV1Beta1Kr8s(dict(metadata=dict(name=name, namespace=self.namespace)))
        try:
            await build.delete(propagation_policy="Foreground")
        except ServerError as e:
            logger.exception(f"Cannot delete build {name} because of {e}")
        return None


class _ShipwrightCache:
    """Utility class for calling the ShipWright k8s cache."""

    def __init__(self, url: str):
        self.url = url
        self.client = httpx.AsyncClient(timeout=10)

    async def list_build_runs(self) -> list[BuildRun]:
        """Get a list of ShipWright BuildRuns."""
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
        """Get a ShipWright BuildRun."""
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


class ShipwrightClient:
    """The K8s client that combines a base client and a cache.

    No authentication or authorization is performed - this is the responsibility of the caller.
    """

    def __init__(
        self,
        namespace: str,
        cache_url: str | None,
        # NOTE: If cache skipping is enabled then when the cache fails a large number of
        # buildruns can overload the k8s API by submitting a lot of calls directly.
        skip_cache_if_unavailable: bool = False,
    ) -> None:
        self.cache = _ShipwrightCache(url=cache_url) if cache_url else None
        self.base_client = _ShipwrightClientBase(namespace=namespace)
        self.skip_cache_if_unavailable = skip_cache_if_unavailable

    async def list_build_runs(self) -> list[BuildRun]:
        """Get a list of ShipWright BuildRuns."""
        if self.cache is None:
            return await self.base_client.list_build_runs()

        try:
            return await self.cache.list_build_runs()
        except CacheError:
            if self.skip_cache_if_unavailable:
                logger.warning("Skipping the cache to list BuildRuns")
                return await self.base_client.list_build_runs()
            else:
                raise

    async def get_build_run(self, name: str) -> BuildRun | None:
        """Get a ShipWright BuildRun."""
        if self.cache is None:
            return await self.base_client.get_build_run(name)

        try:
            return await self.cache.get_build_run(name)
        except CacheError:
            if self.skip_cache_if_unavailable:
                return await self.base_client.get_build_run(name)
            else:
                raise

    async def create_build_run(self, manifest: BuildRun) -> BuildRun:
        """Create a new ShipWright BuildRun."""
        return await self.base_client.create_build_run(manifest)

    async def delete_build_run(self, name: str) -> None:
        """Delete a ShipWright BuildRun."""
        return await self.base_client.delete_build_run(name)

    async def create_image_build(self, params: models.ShipWrightBuildRunParams) -> None:
        """Create a new BuildRun in ShipWright to support a newly created build."""
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
                    )
                )
            ),
        )
        await self.create_build_run(build_run)

    async def update_image_build_status(self, buildrun_name: str) -> models.ShipWrightBuildStatusUpdate:
        """Update the status of a build by pulling the corresponding BuildRun from ShipWright."""
        k8s_build = await self.get_build_run(name=buildrun_name)

        if k8s_build is None:
            return models.ShipWrightBuildStatusUpdate(
                update=models.ShipWrightBuildStatusUpdateContent(status=models.BuildStatus.failed)
            )

        k8s_build_status = k8s_build.status
        completion_time = k8s_build_status.completionTime if k8s_build_status else None

        if k8s_build_status is None or completion_time is None:
            return models.ShipWrightBuildStatusUpdate(update=None)

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
            return models.ShipWrightBuildStatusUpdate(
                update=models.ShipWrightBuildStatusUpdateContent(
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
            return models.ShipWrightBuildStatusUpdate(
                update=models.ShipWrightBuildStatusUpdateContent(
                    status=models.BuildStatus.failed,
                    completed_at=completion_time,
                )
            )

    async def cancel_image_build(self, buildrun_name: str) -> None:
        """Cancel a build by deleting the corresponding BuildRun from ShipWright."""
        # TODO: use proper cancellation, see: https://shipwright.io/docs/build/buildrun/#canceling-a-buildrun
        await self.delete_build_run(name=buildrun_name)
