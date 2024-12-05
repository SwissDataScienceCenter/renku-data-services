"""K8s client for kpack."""

import logging

from kr8s import NotFoundError, ServerError
from kr8s.asyncio.objects import APIObject
from kubernetes.client import ApiClient

from renku_data_services.errors.errors import CannotStartBuildError, DeleteBuildError
from renku_data_services.notebooks.errors.intermittent import IntermittentError
from renku_data_services.notebooks.util.retries import retry_with_exponential_backoff_async
from renku_data_services.session.kpack_crs import Build, Image


class KpackImageV1Alpha2Kr8s(APIObject):
    """Spec for kpack images used by the k8s client."""

    kind: str = "Image"
    version: str = "kpack.io/v1alpha2"
    namespaced: bool = True
    plural: str = "images"
    singular: str = "image"
    scalable: bool = False
    endpoint: str = "image"


class KpackBuildV1Alpha2Kr8s(APIObject):
    """Spec for kpack build used by the k8s client."""

    kind: str = "Build"
    version: str = "kpack.io/v1alpha2"
    namespaced: bool = True
    plural: str = "builds"
    singular: str = "build"
    scalable: bool = False
    endpoint: str = "build"


class KpackClient:
    """Client for creating kpack resources in kubernetes."""

    def __init__(self, namespace: str) -> None:
        self.namespace = namespace
        self.sanitize = ApiClient().sanitize_for_serialization

    async def create_build(self, manifest: Build) -> Build:
        """Create a new image build."""
        manifest.metadata.namespace = self.namespace
        build = await KpackBuildV1Alpha2Kr8s(manifest.model_dump(exclude_none=True, mode="json"))
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
            build = await KpackBuildV1Alpha2Kr8s.get(name=name, namespace=self.namespace)
        except NotFoundError:
            return None
        except ServerError as e:
            if not e.response or e.response.status_code not in [400, 404]:
                logging.exception(f"Cannot get the build {name} because of {e}")
                raise IntermittentError(f"Cannot get build {name} from the k8s API.")
            return None
        return Build.model_validate(build.to_dict())

    async def list_builds(self, label_selector: str | None = None) -> list[Build]:
        """Get a list of kpack builds."""
        try:
            builds = await KpackBuildV1Alpha2Kr8s.list(namespace=self.namespace, label_selector=label_selector)
        except ServerError as e:
            if not e.response or e.response.status_code not in [400, 404]:
                logging.exception(f"Cannot list builds because of {e}")
                raise IntermittentError("Cannot list builds")
            return []
        output = [Build.model_validate(b.to_dict()) for b in builds]
        return output

    async def delete_build(self, name: str) -> None:
        """Delete a kpack build."""
        build = await KpackBuildV1Alpha2Kr8s(dict(metadata=dict(name=name, namespace=self.namespace)))
        try:
            await build.delete(propagation_policy="Foreground")
        except ServerError as e:
            logging.exception(f"Cannot delete build {name} because of {e}")
            raise DeleteBuildError()
        return None

    async def create_image(self, manifest: Image) -> Image:
        """Create a new image image."""
        manifest.metadata.namespace = self.namespace
        image = await KpackImageV1Alpha2Kr8s(manifest.model_dump(exclude_none=True, mode="json"))
        image_name = manifest.metadata.name
        try:
            await image.create()
        except ServerError as e:
            logging.exception(f"Cannot create the image image {image_name} because of {e}")
            raise CannotStartBuildError(message=f"Cannot create the kpack image {image_name}")
        await image.refresh()
        image_resource = await retry_with_exponential_backoff_async(lambda x: x is None)(self.get_image)(image_name)
        if image_resource is None:
            raise CannotStartBuildError(message=f"Cannot create the kpack image {image_name}")
        return image_resource

    async def get_image(self, name: str) -> Image | None:
        """Get an image image."""
        try:
            image = await KpackImageV1Alpha2Kr8s.get(name=name, namespace=self.namespace)
        except NotFoundError:
            return None
        except ServerError as e:
            if not e.response or e.response.status_code not in [400, 404]:
                logging.exception(f"Cannot get the image {name} because of {e}")
                raise IntermittentError(f"Cannot get image {name} from the k8s API.")
            return None
        return Image.model_validate(image.to_dict())

    async def list_images(self, label_selector: str | None = None) -> list[Image]:
        """Get a list of kpack images."""
        try:
            images = await KpackImageV1Alpha2Kr8s.list(namespace=self.namespace, label_selector=label_selector)
        except ServerError as e:
            if not e.response or e.response.status_code not in [400, 404]:
                logging.exception(f"Cannot list images because of {e}")
                raise IntermittentError("Cannot list images")
            return []
        output = [Image.model_validate(b.to_dict()) for b in images]
        return output

    async def delete_image(self, name: str) -> None:
        """Delete a kpack image."""
        image = await KpackImageV1Alpha2Kr8s(dict(metadata=dict(name=name, namespace=self.namespace)))
        try:
            await image.delete(propagation_policy="Foreground")
        except ServerError as e:
            logging.exception(f"Cannot delete image {name} because of {e}")
            raise DeleteBuildError()
        return None
