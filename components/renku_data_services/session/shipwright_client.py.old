"""K8s client for shipwright."""

import logging
from urllib.parse import urljoin

import httpx
from kr8s import NotFoundError, ServerError
from kr8s.asyncio.objects import APIObject
from kubernetes.client import ApiClient

from renku_data_services.errors.errors import CannotStartBuildError, DeleteBuildError, ProgrammingError
from renku_data_services.notebooks.errors.intermittent import CacheError, IntermittentError
from renku_data_services.notebooks.util.retries import retry_with_exponential_backoff_async
from renku_data_services.session.shipwright_crs import Build, BuildRun


class ShipwrightBuildV1Beta2Kr8s(APIObject):
    """Spec for shipwright build used by the k8s client."""

    kind: str = "Build"
    version: str = "shipwright.io/v1beta1"
    namespaced: bool = True
    plural: str = "builds"
    singular: str = "build"
    scalable: bool = False
    endpoint: str = "builds"


class ShipwrightBuildRunV1Beta2Kr8s(APIObject):
    """Spec for shipwright build used by the k8s client."""

    kind: str = "BuildRun"
    version: str = "shipwright.io/v1beta1"
    namespaced: bool = True
    plural: str = "buildruns"
    singular: str = "buildrun"
    scalable: bool = False
    endpoint: str = "buildruns"


class ShipwrightClient:
    """Client for creating shipwright resources in kubernetes."""

    def __init__(self, namespace: str) -> None:
        self.namespace = namespace
        self.sanitize = ApiClient().sanitize_for_serialization

    async def create_build(self, manifest: Build) -> Build:
        """Create a new build."""
        manifest.metadata.namespace = self.namespace
        build = await ShipwrightBuildV1Beta2Kr8s(manifest.model_dump(exclude_none=True, mode="json"))
        build_name = manifest.metadata.name
        try:
            await build.create()
        except ServerError as e:
            logging.exception(f"Cannot create the image build {build_name} because of {e}")
            raise CannotStartBuildError(message=f"Cannot create the image build {build_name}")
        await build.refresh()
        build_resource = await retry_with_exponential_backoff_async(lambda x: x is None)(self.get_build)(build_name)
        if build_resource is None:
            raise CannotStartBuildError(message=f"Cannot create the image build {build_name}")
        return build_resource

    async def get_build(self, name: str) -> Build | None:
        """Get an image build."""
        try:
            build = await ShipwrightBuildV1Beta2Kr8s.get(name=name, namespace=self.namespace)
        except NotFoundError:
            return None
        except ServerError as e:
            if not e.response or e.response.status_code not in [400, 404]:
                logging.exception(f"Cannot get the build {name} because of {e}")
                raise IntermittentError(f"Cannot get build {name} from the k8s API.")
            return None
        return Build.model_validate(build.to_dict())

    async def list_builds(self, label_selector: str | None = None) -> list[Build]:
        """Get a list of shipwright builds."""
        try:
            builds = await ShipwrightBuildV1Beta2Kr8s.list(namespace=self.namespace, label_selector=label_selector)
        except ServerError as e:
            if not e.response or e.response.status_code not in [400, 404]:
                logging.exception(f"Cannot list builds because of {e}")
                raise IntermittentError("Cannot list builds")
            return []
        output = [Build.model_validate(b.to_dict()) for b in builds]
        return output

    async def delete_build(self, name: str) -> None:
        """Delete a shipwright build."""
        build = await ShipwrightBuildV1Beta2Kr8s(dict(metadata=dict(name=name, namespace=self.namespace)))
        try:
            await build.delete(propagation_policy="Foreground")
        except ServerError as e:
            logging.exception(f"Cannot delete build {name} because of {e}")
            raise DeleteBuildError()
        return None

    async def create_build_run(self, manifest: BuildRun) -> BuildRun:
        """Create a new build run."""
        manifest.metadata.namespace = self.namespace
        build_run = await ShipwrightBuildRunV1Beta2Kr8s(manifest.model_dump(exclude_none=True, mode="json"))
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
        """Get an image build run."""
        try:
            build = await ShipwrightBuildRunV1Beta2Kr8s.get(name=name, namespace=self.namespace)
        except NotFoundError:
            return None
        except ServerError as e:
            if not e.response or e.response.status_code not in [400, 404]:
                logging.exception(f"Cannot get the build {name} because of {e}")
                raise IntermittentError(f"Cannot get build {name} from the k8s API.")
            return None
        return BuildRun.model_validate(build.to_dict())

    async def get_build_run_raw(self, name: str) -> ShipwrightBuildRunV1Beta2Kr8s | None:
        """Get an image build run."""
        try:
            build = await ShipwrightBuildRunV1Beta2Kr8s.get(name=name, namespace=self.namespace)
        except NotFoundError:
            return None
        except ServerError as e:
            if not e.response or e.response.status_code not in [400, 404]:
                logging.exception(f"Cannot get the build {name} because of {e}")
                raise IntermittentError(f"Cannot get build {name} from the k8s API.")
            return None
        return build

    async def list_build_runs(self, label_selector: str | None = None) -> list[BuildRun]:
        """Get a list of shipwright build runs."""
        try:
            builds = await ShipwrightBuildRunV1Beta2Kr8s.list(namespace=self.namespace, label_selector=label_selector)
        except ServerError as e:
            if not e.response or e.response.status_code not in [400, 404]:
                logging.exception(f"Cannot list builds because of {e}")
                raise IntermittentError("Cannot list builds")
            return []
        output = [BuildRun.model_validate(b.to_dict()) for b in builds]
        return output

    async def delete_build_run(self, name: str) -> None:
        """Delete a shipwright build run."""
        build = await ShipwrightBuildRunV1Beta2Kr8s(dict(metadata=dict(name=name, namespace=self.namespace)))
        try:
            await build.delete(propagation_policy="Foreground")
        except ServerError as e:
            logging.exception(f"Cannot delete build {name} because of {e}")
            raise DeleteBuildError()
        return None


class ShipwrightCache:
    """Utility class for calling the shipwright k8s cache."""

    def __init__(self, url: str):
        self.url = url
        self.client = httpx.AsyncClient(timeout=10)

    async def list_buildruns(self, name: str) -> list[BuildRun]:
        """List the jupyter servers."""
        url = urljoin(self.url, f"/buildruns/{name}")
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

    async def get_server(self, name: str) -> BuildRun | None:
        """Get a specific jupyter server."""
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
