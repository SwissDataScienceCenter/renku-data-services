"""Data connectors blueprint."""

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from kubernetes.client import V1Affinity, V1Toleration
from sanic import Request
from sanic.response import HTTPResponse, JSONResponse
from sanic_ext import validate
from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.base_api.auth import (
    authenticate,
    only_authenticated,
)
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.etag import extract_if_none_match, if_match_required
from renku_data_services.base_api.misc import validate_query
from renku_data_services.base_api.pagination import PaginationRequest, paginate
from renku_data_services.base_models.core import (
    DataConnectorInProjectPath,
    DataConnectorPath,
    NamespacePath,
    ProjectPath,
    Slug,
)
from renku_data_services.base_models.metrics import MetricsService
from renku_data_services.base_models.validation import validate_and_dump, validated_json
from renku_data_services.connected_services.db import ConnectedServicesRepository
from renku_data_services.connected_services.models import ProviderKind
from renku_data_services.data_connectors import apispec, models
from renku_data_services.data_connectors.core import (
    create_deposit_upload,
    dump_storage_with_sensitive_fields,
    prevalidate_unsaved_global_data_connector,
    serialize_deposit,
    transform_secrets_for_back_end,
    transform_secrets_for_front_end,
    update_deposit_status,
    update_deposits_statuses,
    validate_data_connector_patch,
    validate_data_connector_secrets_patch,
    validate_deposit,
    validate_deposit_patch,
    validate_unsaved_data_connector,
)
from renku_data_services.data_connectors.db import (
    DataConnectorRepository,
    DataConnectorSecretRepository,
)
from renku_data_services.data_connectors.deposits.zenodo import ZenodoAPIClient
from renku_data_services.k8s.client_interfaces import K8sClient, SecretClient
from renku_data_services.k8s.clients import DepositUploadJobClient
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER
from renku_data_services.k8s.models import GVK, K8sObjectMeta
from renku_data_services.notebooks.data_sources import DataSourceRepository
from renku_data_services.storage.rclone import RCloneValidator


@dataclass(kw_only=True)
class DataConnectorsBP(CustomBlueprint):
    """Handlers for manipulating data connectors."""

    data_connector_repo: DataConnectorRepository
    data_connector_secret_repo: DataConnectorSecretRepository
    authenticator: base_models.Authenticator
    metrics: MetricsService
    job_client: DepositUploadJobClient
    secret_client: SecretClient
    zenodo_client: ZenodoAPIClient
    connected_services_repo: ConnectedServicesRepository
    oauth_http_client_factory: OAuthHttpClientFactory
    data_source_repo: DataSourceRepository
    dc_storage_class: str
    data_service_base_url: str
    k8s_client: K8sClient
    deposit_job_affinity: V1Affinity
    deposit_job_tolerations: list[V1Toleration]

    def get_all(self) -> BlueprintFactoryResponse:
        """List data connectors."""

        @authenticate(self.authenticator)
        @validate_query(query=apispec.DataConnectorsGetQuery)
        @paginate
        async def _get_all(
            _: Request,
            user: base_models.APIUser,
            pagination: PaginationRequest,
            query: apispec.DataConnectorsGetQuery,
            validator: RCloneValidator,
        ) -> tuple[list[dict[str, Any]], int]:
            ns_segments = query.namespace.split("/")
            ns: None | NamespacePath | ProjectPath
            if len(ns_segments) == 0 or (len(ns_segments) == 1 and len(ns_segments[0]) == 0):
                ns = None
            elif len(ns_segments) == 1 and len(ns_segments[0]) > 0:
                ns = NamespacePath.from_strings(*ns_segments)
            elif len(ns_segments) == 2:
                ns = ProjectPath.from_strings(*ns_segments)
            else:
                raise errors.ValidationError(
                    message="Got an unexpected number of path segments for the data connector namespace"
                    " in the request query parameter, expected 0, 1 or 2"
                )

            data_connectors, total_num = await self.data_connector_repo.get_data_connectors(
                user=user, pagination=pagination, namespace=ns
            )
            return [
                validate_and_dump(
                    apispec.DataConnector,
                    self._dump_data_connector(dc, validator=validator),
                )
                for dc in data_connectors
            ], total_num

        return "/data_connectors", ["GET"], _get_all

    def post(self) -> BlueprintFactoryResponse:
        """Create a new data connector."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.DataConnectorPost)
        async def _post(
            _: Request, user: base_models.APIUser, body: apispec.DataConnectorPost, validator: RCloneValidator
        ) -> JSONResponse:
            data_connector = await validate_unsaved_data_connector(body, validator=validator)
            result = await self.data_connector_repo.insert_namespaced_data_connector(
                user=user, data_connector=data_connector
            )
            await self.metrics.data_connector_created(user)
            return validated_json(
                apispec.DataConnector,
                self._dump_data_connector(result, validator=validator),
                status=201,
            )

        return "/data_connectors", ["POST"], _post

    def post_global(self) -> BlueprintFactoryResponse:
        """Create a new global data connector."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.GlobalDataConnectorPost)
        async def _post_global(
            _: Request, user: base_models.APIUser, body: apispec.GlobalDataConnectorPost, validator: RCloneValidator
        ) -> JSONResponse:
            data_connector = await prevalidate_unsaved_global_data_connector(body, validator=validator)
            result, inserted = await self.data_connector_repo.insert_global_data_connector(
                user=user, prevalidated_dc=data_connector, validator=validator
            )
            return validated_json(
                apispec.DataConnector,
                self._dump_data_connector(result, validator=validator),
                status=201 if inserted else 200,
            )

        return "/data_connectors/global", ["POST"], _post_global

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific data connector."""

        @authenticate(self.authenticator)
        @extract_if_none_match
        async def _get_one(
            _: Request, user: base_models.APIUser, data_connector_id: ULID, etag: str | None, validator: RCloneValidator
        ) -> HTTPResponse:
            data_connector = await self.data_connector_repo.get_data_connector(
                user=user, data_connector_id=data_connector_id
            )

            if data_connector.etag == etag:
                return HTTPResponse(status=304)

            headers = {"ETag": data_connector.etag}
            return validated_json(
                apispec.DataConnector,
                self._dump_data_connector(data_connector, validator=validator),
                headers=headers,
            )

        return "/data_connectors/<data_connector_id:ulid>", ["GET"], _get_one

    def get_one_global_by_slug(self) -> BlueprintFactoryResponse:
        """Get a specific global data connector by slug."""

        @authenticate(self.authenticator)
        @extract_if_none_match
        async def _get_one_global_by_slug(
            _: Request,
            user: base_models.APIUser,
            slug: Slug,
            etag: str | None,
            validator: RCloneValidator,
        ) -> HTTPResponse:
            data_connector = await self.data_connector_repo.get_global_data_connector_by_slug(user=user, slug=slug)

            if data_connector.etag == etag:
                return HTTPResponse(status=304)

            headers = {"ETag": data_connector.etag}
            return validated_json(
                apispec.DataConnector,
                self._dump_data_connector(data_connector, validator=validator),
                headers=headers,
            )

        return "/data_connectors/global/<slug:renku_slug>", ["GET"], _get_one_global_by_slug

    def get_one_by_slug(self) -> BlueprintFactoryResponse:
        """Get a specific data connector by namespace/entity slug."""

        @authenticate(self.authenticator)
        @extract_if_none_match
        async def _get_one_by_slug(
            _: Request,
            user: base_models.APIUser,
            namespace: str,
            slug: Slug,
            etag: str | None,
            validator: RCloneValidator,
        ) -> HTTPResponse:
            data_connector = await self.data_connector_repo.get_data_connector_by_slug(
                user=user,
                path=DataConnectorPath.from_strings(namespace, slug.value),
            )

            if data_connector.etag == etag:
                return HTTPResponse(status=304)

            headers = {"ETag": data_connector.etag}
            return validated_json(
                apispec.DataConnector,
                self._dump_data_connector(data_connector, validator=validator),
                headers=headers,
            )

        return "/namespaces/<namespace>/data_connectors/<slug:renku_slug>", ["GET"], _get_one_by_slug

    def get_one_by_slug_from_project_namespace(self) -> BlueprintFactoryResponse:
        """Get a specific data connector by namespace/project_slug/dc_slug slug."""

        @authenticate(self.authenticator)
        @extract_if_none_match
        async def _get_one_from_project_namespace(
            _: Request,
            user: base_models.APIUser,
            ns_slug: Slug,
            project_slug: Slug,
            dc_slug: Slug,
            etag: str | None,
            validator: RCloneValidator,
        ) -> HTTPResponse:
            dc_path = DataConnectorInProjectPath.from_strings(
                ns_slug.value,
                project_slug.value,
                dc_slug.value,
            )
            data_connector = await self.data_connector_repo.get_data_connector_by_slug(user=user, path=dc_path)

            if data_connector.etag == etag:
                return HTTPResponse(status=304)

            headers = {"ETag": data_connector.etag}
            return validated_json(
                apispec.DataConnector,
                self._dump_data_connector(data_connector, validator=validator),
                headers=headers,
            )

        return (
            "/namespaces/<ns_slug:renku_slug>/projects/<project_slug:renku_slug>/data_connectors/<dc_slug:renku_slug>",
            ["GET"],
            _get_one_from_project_namespace,
        )

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a data connector."""

        @authenticate(self.authenticator)
        @only_authenticated
        @if_match_required
        @validate(json=apispec.DataConnectorPatch)
        async def _patch(
            _: Request,
            user: base_models.APIUser,
            data_connector_id: ULID,
            body: apispec.DataConnectorPatch,
            etag: str,
            validator: RCloneValidator,
        ) -> JSONResponse:
            existing_dc = await self.data_connector_repo.get_data_connector(
                user=user, data_connector_id=data_connector_id
            )
            dc_patch = validate_data_connector_patch(existing_dc, body, validator=validator)
            data_connector_update = await self.data_connector_repo.update_data_connector(
                user=user, data_connector_id=data_connector_id, patch=dc_patch, etag=etag
            )

            return validated_json(
                apispec.DataConnector,
                self._dump_data_connector(data_connector_update.new, validator=validator),
            )

        return "/data_connectors/<data_connector_id:ulid>", ["PATCH"], _patch

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a data connector."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete(
            _: Request,
            user: base_models.APIUser,
            data_connector_id: ULID,
        ) -> HTTPResponse:
            await self.data_connector_repo.delete_data_connector(user=user, data_connector_id=data_connector_id)
            return HTTPResponse(status=204)

        return "/data_connectors/<data_connector_id:ulid>", ["DELETE"], _delete

    def get_permissions(self) -> BlueprintFactoryResponse:
        """Get the permissions of the current user on the data connector."""

        @authenticate(self.authenticator)
        async def _get_permissions(_: Request, user: base_models.APIUser, data_connector_id: ULID) -> JSONResponse:
            permissions = await self.data_connector_repo.get_data_connector_permissions(
                user=user, data_connector_id=data_connector_id
            )
            return validated_json(apispec.DataConnectorPermissions, permissions)

        return "/data_connectors/<data_connector_id:ulid>/permissions", ["GET"], _get_permissions

    def get_all_project_links(self) -> BlueprintFactoryResponse:
        """List all links from a given data connector to projects."""

        @authenticate(self.authenticator)
        async def _get_all_project_links(
            _: Request,
            user: base_models.APIUser,
            data_connector_id: ULID,
        ) -> JSONResponse:
            links = await self.data_connector_repo.get_links_from(user=user, data_connector_id=data_connector_id)
            return validated_json(
                apispec.DataConnectorToProjectLinksList,
                [self._dump_data_connector_to_project_link(link) for link in links],
            )

        return "/data_connectors/<data_connector_id:ulid>/project_links", ["GET"], _get_all_project_links

    def post_project_link(self) -> BlueprintFactoryResponse:
        """Create a new link from a data connector to a project."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.DataConnectorToProjectLinkPost)
        async def _post_project_link(
            _: Request,
            user: base_models.APIUser,
            data_connector_id: ULID,
            body: apispec.DataConnectorToProjectLinkPost,
        ) -> JSONResponse:
            unsaved_link = models.UnsavedDataConnectorToProjectLink(
                data_connector_id=data_connector_id,
                project_id=ULID.from_str(body.project_id),
            )
            link = await self.data_connector_repo.insert_link(user=user, link=unsaved_link)
            await self.metrics.data_connector_linked(user)
            return validated_json(
                apispec.DataConnectorToProjectLink, self._dump_data_connector_to_project_link(link), status=201
            )

        return "/data_connectors/<data_connector_id:ulid>/project_links", ["POST"], _post_project_link

    def delete_project_link(self) -> BlueprintFactoryResponse:
        """Delete a link from a data connector to a project."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete_project_link(
            _: Request,
            user: base_models.APIUser,
            data_connector_id: ULID,
            link_id: ULID,
        ) -> HTTPResponse:
            await self.data_connector_repo.delete_link(user=user, data_connector_id=data_connector_id, link_id=link_id)
            return HTTPResponse(status=204)

        return (
            "/data_connectors/<data_connector_id:ulid>/project_links/<link_id:ulid>",
            ["DELETE"],
            _delete_project_link,
        )

    def get_all_data_connectors_links_to_project(self) -> BlueprintFactoryResponse:
        """List all links from data connectors to a given project."""

        @authenticate(self.authenticator)
        async def _get_all_data_connectors_links_to_project(
            _: Request,
            user: base_models.APIUser,
            project_id: ULID,
        ) -> JSONResponse:
            links = await self.data_connector_repo.get_links_to(user=user, project_id=project_id)
            return validated_json(
                apispec.DataConnectorToProjectLinksList,
                [self._dump_data_connector_to_project_link(link) for link in links],
            )

        return "/projects/<project_id:ulid>/data_connector_links", ["GET"], _get_all_data_connectors_links_to_project

    def get_inaccessible_data_connectors_links_to_project(self) -> BlueprintFactoryResponse:
        """The number of data connector links in a given project the user has no access to."""

        @authenticate(self.authenticator)
        async def _get_inaccessible_data_connectors_links_to_project(
            _: Request,
            user: base_models.APIUser,
            project_id: ULID,
        ) -> JSONResponse:
            link_ids = await self.data_connector_repo.get_inaccessible_links_to_project(
                user=user, project_id=project_id
            )
            return validated_json(apispec.InaccessibleDataConnectorLinks, {"count": len(link_ids)})

        return (
            "/projects/<project_id:ulid>/inaccessible_data_connector_links",
            ["GET"],
            _get_inaccessible_data_connectors_links_to_project,
        )

    def get_secrets(self) -> BlueprintFactoryResponse:
        """List all saved secrets for a data connector."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _get_secrets(
            _: Request,
            user: base_models.APIUser,
            data_connector_id: ULID,
        ) -> JSONResponse:
            secrets = await self.data_connector_secret_repo.get_data_connector_secrets(
                user=user, data_connector_id=data_connector_id
            )
            data_connector = await self.data_connector_repo.get_data_connector(
                user=user, data_connector_id=data_connector_id
            )
            return validated_json(
                apispec.DataConnectorSecretsList,
                [
                    self._dump_data_connector_secret(secret)
                    for secret in transform_secrets_for_front_end(secrets, data_connector.storage)
                ],
            )

        return "/data_connectors/<data_connector_id:ulid>/secrets", ["GET"], _get_secrets

    def patch_secrets(self) -> BlueprintFactoryResponse:
        """Create, update or delete saved secrets for a data connector."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.DataConnectorSecretPatchList)
        async def _patch_secrets(
            _: Request,
            user: base_models.APIUser,
            data_connector_id: ULID,
            body: apispec.DataConnectorSecretPatchList,
        ) -> JSONResponse:
            unsaved_secrets = validate_data_connector_secrets_patch(put=body)
            data_connector = await self.data_connector_repo.get_data_connector(
                user=user, data_connector_id=data_connector_id
            )
            storage = data_connector.storage

            unsaved_secrets, expiration_timestamp = await transform_secrets_for_back_end(unsaved_secrets, storage)

            secrets = await self.data_connector_secret_repo.patch_data_connector_secrets(
                user=user,
                data_connector_id=data_connector_id,
                secrets=unsaved_secrets,
                expiration_timestamp=expiration_timestamp,
            )
            return validated_json(
                apispec.DataConnectorSecretsList,
                [
                    self._dump_data_connector_secret(secret)
                    for secret in transform_secrets_for_front_end(secrets, storage)
                ],
            )

        return "/data_connectors/<data_connector_id:ulid>/secrets", ["PATCH"], _patch_secrets

    def delete_secrets(self) -> BlueprintFactoryResponse:
        """Delete all saved secrets for a data connector."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete_secrets(
            _: Request,
            user: base_models.APIUser,
            data_connector_id: ULID,
        ) -> HTTPResponse:
            await self.data_connector_secret_repo.delete_data_connector_secrets(
                user=user, data_connector_id=data_connector_id
            )
            return HTTPResponse(status=204)

        return "/data_connectors/<data_connector_id:ulid>/secrets", ["DELETE"], _delete_secrets

    @staticmethod
    def _dump_data_connector(
        data_connector: models.DataConnector | models.GlobalDataConnector, validator: RCloneValidator
    ) -> dict[str, Any]:
        """Dumps a data connector for API responses."""
        storage = dump_storage_with_sensitive_fields(data_connector.storage, validator=validator)
        if data_connector.namespace is None:
            return dict(
                id=str(data_connector.id),
                name=data_connector.name,
                slug=data_connector.slug,
                storage=storage,
                creation_date=data_connector.creation_date,
                created_by=data_connector.created_by,
                visibility=data_connector.visibility.value,
                description=data_connector.description,
                etag=data_connector.etag,
                keywords=data_connector.keywords or [],
                doi=data_connector.doi,
                publisher_name=data_connector.publisher_name,
                publisher_url=data_connector.publisher_url,
            )
        return dict(
            id=str(data_connector.id),
            name=data_connector.name,
            namespace=data_connector.namespace.path.serialize(),
            slug=data_connector.slug,
            storage=storage,
            # secrets=,
            creation_date=data_connector.creation_date,
            created_by=data_connector.created_by,
            visibility=data_connector.visibility.value,
            description=data_connector.description,
            etag=data_connector.etag,
            keywords=data_connector.keywords or [],
        )

    @staticmethod
    def _dump_data_connector_to_project_link(link: models.DataConnectorToProjectLink) -> dict[str, Any]:
        """Dumps a link from a data connector to a project for API responses."""
        return dict(
            id=str(link.id),
            data_connector_id=str(link.data_connector_id),
            project_id=str(link.project_id),
            creation_date=link.creation_date,
            created_by=link.created_by,
        )

    @staticmethod
    def _dump_data_connector_secret(secret: models.DataConnectorSecret) -> dict[str, Any]:
        """Dumps a data connector secret for API responses."""
        return dict(
            name=secret.name,
            secret_id=str(secret.secret_id),
        )

    async def __get_zenodo_access_token(self, user: base_models.APIUser) -> str:
        provider = await self.connected_services_repo.get_provider_for_kind(user, ProviderKind.zenodo)
        if not provider:
            raise errors.UnauthorizedError(
                message="The zenodo provider does not exist, please contact your administrator to set this up."
            )
        if not provider.connected_user:
            raise errors.UnauthorizedError(
                message="You need to connect and autheticate with the zenodo provider to do this"
            )
        token_set = await self.connected_services_repo.get_token_set(
            user=user, connection_id=provider.connected_user.connection.id
        )
        if not token_set:
            raise errors.UnauthorizedError(
                message="You need to connect and autheticate with the zenodo provider to do this"
            )
        access_token = token_set.access_token
        if not access_token:
            raise errors.UnauthorizedError(
                message="You need to connect and autheticate with the zenodo provider to do this"
            )
        return access_token

    def post_deposit(self) -> BlueprintFactoryResponse:
        """Create a deposit."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.DepositPost)
        async def _post_deposit(
            request: Request,
            user: base_models.AuthenticatedAPIUser,
            body: apispec.DepositPost,
        ) -> JSONResponse:
            # Get token for Zenodo
            token = await self.__get_zenodo_access_token(user)
            # Create deposit in Zenodo
            zenodo_dep = await self.zenodo_client.create_deposit(token, body.name)
            # Create the deposit in the DB
            dep = await validate_deposit(user, body, str(zenodo_dep.id), self.data_connector_repo)
            job_name = "deposit-" + str(ULID()).lower()
            dep_job = models.UnsavedDepositJob(
                deposit=dep,
                name=job_name,
                cluster_id=DEFAULT_K8S_CLUSTER,
            )
            saved_dep = await self.data_connector_repo.create_deposit(user, dep_job)
            namespace = os.environ.get("K8S_NAMESPACE", "default")
            # Create the job in kubernetes
            dc = await self.data_connector_repo.get_data_connector(
                user=user, data_connector_id=ULID.from_str(body.data_connector_id)
            )
            secrets = await self.data_connector_secret_repo.get_data_connector_secrets(user, dc.id)

            async def dc_iter() -> AsyncIterator[models.DataConnectorWithSecrets]:
                yield dc.with_secrets(secrets)

            extras = await self.data_source_repo.get_data_sources(
                request=request,
                user=user,
                base_name=saved_dep.name,
                data_connectors_stream=dc_iter(),
                work_dir=PurePosixPath(),
                data_connectors_overrides=[],
                namespace=namespace,
                storage_class=self.dc_storage_class,
            )
            await create_deposit_upload(
                user=user,
                extras=extras,
                storage_class=self.dc_storage_class,
                namespace=namespace,
                cluster_id=saved_dep.cluster_id,
                k8s_client=self.k8s_client,
                data_service_base_url=self.data_service_base_url,
                deposit_job=saved_dep,
                job_client=self.job_client,
                deposit_api_key=token,
                deposit_job_tolerations=self.deposit_job_tolerations,
                deposit_job_affinity=self.deposit_job_affinity,
            )
            return validated_json(apispec.Deposit, serialize_deposit(saved_dep))

        return "/deposits", ["POST"], _post_deposit

    def get_deposit(self) -> BlueprintFactoryResponse:
        """Get a specific deposit."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _get_deposit(_: Request, user: base_models.AuthenticatedAPIUser, deposit_id: ULID) -> JSONResponse:
            namespace = os.environ.get("K8S_NAMESPACE", "default")
            saved_dep = await self.data_connector_repo.get_deposit(user, deposit_id)
            saved_dep = await update_deposit_status(
                user=user,
                deposit_job=saved_dep,
                dc_repo=self.data_connector_repo,
                job_client=self.job_client,
                namespace=namespace,
            )
            return validated_json(apispec.Deposit, serialize_deposit(saved_dep))

        return "/deposits/<deposit_id:ulid>", ["GET"], _get_deposit

    def patch_deposit(self) -> BlueprintFactoryResponse:
        """Patch a specific deposit."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.DepositPatch)
        async def _patch_deposit(
            _: Request, user: base_models.AuthenticatedAPIUser, body: apispec.DepositPatch, deposit_id: ULID
        ) -> JSONResponse:
            namespace = os.environ.get("K8S_NAMESPACE", "default")
            patch = validate_deposit_patch(body)
            saved_dep = await self.data_connector_repo.update_deposit(user, deposit_id, patch)
            saved_dep = await update_deposit_status(
                user=user,
                deposit_job=saved_dep,
                dc_repo=self.data_connector_repo,
                job_client=self.job_client,
                namespace=namespace,
            )
            # TODO: When the deposit is completed create a new data connector
            return validated_json(apispec.Deposit, serialize_deposit(saved_dep))

        return "/deposits/<deposit_id:ulid>", ["PATCH"], _patch_deposit

    def delete_deposit(self) -> BlueprintFactoryResponse:
        """Delete a specific deposit."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete_deposit(_: Request, user: base_models.AuthenticatedAPIUser, deposit_id: ULID) -> HTTPResponse:
            await self.data_connector_repo.delete_deposit(user, deposit_id)
            # TODO: Delete any jobs from k8s
            return HTTPResponse(status=204)

        return "/deposits/<deposit_id:ulid>", ["DELETE"], _delete_deposit

    def get_deposits(self) -> BlueprintFactoryResponse:
        """Get a specific deposit."""

        @authenticate(self.authenticator)
        @only_authenticated
        @paginate
        async def _get_deposits(
            _: Request, user: base_models.AuthenticatedAPIUser, pagination: PaginationRequest
        ) -> tuple[list[dict[str, Any]], int]:
            namespace = os.environ.get("K8S_NAMESPACE", "default")
            deposits, total_num = await self.data_connector_repo.get_deposits(
                user, data_connector_id=None, pagination=pagination
            )
            deposits = await update_deposits_statuses(
                user=user,
                deposit_jobs=deposits,
                dc_repo=self.data_connector_repo,
                job_client=self.job_client,
                namespace=namespace,
            )
            return [validate_and_dump(apispec.Deposit, serialize_deposit(i)) for i in deposits], total_num

        return "/deposits", ["GET"], _get_deposits

    def get_dc_deposits(self) -> BlueprintFactoryResponse:
        """Get a specific deposit."""

        @authenticate(self.authenticator)
        @only_authenticated
        @paginate
        async def _get_dc_deposits(
            _: Request, user: base_models.AuthenticatedAPIUser, data_connector_id: ULID, pagination: PaginationRequest
        ) -> tuple[list[dict[str, Any]], int]:
            namespace = os.environ.get("K8S_NAMESPACE", "default")
            deposits, total_num = await self.data_connector_repo.get_deposits(user, data_connector_id, pagination)
            deposits = await update_deposits_statuses(
                user=user,
                deposit_jobs=deposits,
                dc_repo=self.data_connector_repo,
                job_client=self.job_client,
                namespace=namespace,
            )
            return [validate_and_dump(apispec.Deposit, serialize_deposit(i)) for i in deposits], total_num

        return "/data_connectors/<data_connector_id:ulid>/deposits", ["GET"], _get_dc_deposits

    def get_dc_deposit_logs(self) -> BlueprintFactoryResponse:
        """Get logs of a specific deposit."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _get_dc_deposit_logs(
            _: Request, user: base_models.AuthenticatedAPIUser, deposit_id: ULID
        ) -> JSONResponse:
            namespace = os.environ.get("K8S_NAMESPACE", "default")
            saved_dep = await self.data_connector_repo.get_deposit(user, deposit_id)
            saved_dep = await update_deposit_status(
                user,
                deposit_job=saved_dep,
                dc_repo=self.data_connector_repo,
                job_client=self.job_client,
                namespace=namespace,
            )
            meta = K8sObjectMeta(
                name=saved_dep.name,
                namespace=namespace,
                cluster=saved_dep.cluster_id,
                gvk=GVK(kind="Job", version="v1", group="batch"),
                user_id=user.id,
            )
            all_logs = await self.job_client.logs(meta)
            output: dict[str, str] = {}
            containers = sorted(all_logs.keys())
            for container in containers:
                logs_iter = all_logs[container]
                logs: list[str] = []
                async for log in logs_iter:
                    logs.append(log)
                output[container] = "\n".join(logs)
            return validated_json(apispec.DepositLogs, output)

        return "/deposits/<deposit_id:ulid>/logs", ["GET"], _get_dc_deposit_logs
