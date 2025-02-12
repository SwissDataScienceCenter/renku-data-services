"""An abstraction over the kr8s kubernetes client and the k8s-watcher."""

import logging
from urllib.parse import urljoin

import httpx
from kr8s import NotFoundError, ServerError
from kr8s.asyncio.objects import APIObject
from kubernetes.client import ApiClient

from renku_data_services.errors.errors import CannotStartBuildError, DeleteBuildError
from renku_data_services.notebooks.errors.intermittent import CacheError, IntermittentError
from renku_data_services.notebooks.errors.programming import ProgrammingError
from renku_data_services.notebooks.util.retries import retry_with_exponential_backoff_async
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


class ShipwrightClientBase:
    """Client for managing ShipWright resources in kubernetes."""

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
            logging.exception(f"Cannot create the image build {build_run_name} because of {e}")
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
                logging.exception(f"Cannot get the build {name} because of {e}")
                raise IntermittentError(f"Cannot get build {name} from the k8s API.")
            return None
        return BuildRun.model_validate(build.to_dict())

    async def list_build_runs(self, label_selector: str | None = None) -> list[BuildRun]:
        """Get a list of ShipWright BuildRuns."""
        try:
            builds = await ShipwrightBuildRunV1Beta1Kr8s.list(namespace=self.namespace, label_selector=label_selector)
        except ServerError as e:
            if not e.response or e.response.status_code not in [400, 404]:
                logging.exception(f"Cannot list builds because of {e}")
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
            logging.exception(f"Cannot delete build {name} because of {e}")
            raise DeleteBuildError()
        return None


class ShipwrightCache:
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
            logging.warning(f"Shipwright k8s cache at {url} cannot be reached: {err}")
            raise CacheError("The shipwright k8s cache is not available")
        if res.status_code != 200:
            logging.warning(
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
            logging.warning(f"Shipwright k8s cache at {url} cannot be reached: {err}")
            raise CacheError("The shipwright k8s cache is not available")
        if res.status_code != 200:
            logging.warning(
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
    """The K8s client that combines a base client and a cache."""

    def __init__(
        self,
        cache: ShipwrightCache | None,
        base_client: ShipwrightClientBase,
        # NOTE: If cache skipping is enabled then when the cache fails a large number of
        # buildruns can overload the k8s API by submitting a lot of calls directly.
        skip_cache_if_unavailable: bool = False,
    ) -> None:
        self.cache = cache
        self.base_client = base_client
        self.skip_cache_if_unavailable = skip_cache_if_unavailable

    async def list_build_runs(self) -> list[BuildRun]:
        """Get a list of ShipWright BuildRuns."""
        if self.cache is None:
            return await self.base_client.list_build_runs()

        try:
            return await self.cache.list_build_runs()
        except CacheError:
            if self.skip_cache_if_unavailable:
                logging.warning("Skipping the cache to list BuildRuns")
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
