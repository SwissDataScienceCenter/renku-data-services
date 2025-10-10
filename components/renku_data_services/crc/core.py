"""crc modules converters and validators."""

from typing import overload
from urllib.parse import urlparse

from ulid import ULID

from renku_data_services.base_models import RESET, ResetType
from renku_data_services.crc import apispec, models
from renku_data_services.errors import errors


def validate_quota(body: apispec.QuotaWithOptionalId) -> models.UnsavedQuota:
    """Validate a quota object."""
    return models.UnsavedQuota(
        cpu=body.cpu,
        memory=body.memory,
        gpu=body.gpu,
    )


def validate_quota_patch(body: apispec.QuotaPatch) -> models.QuotaPatch:
    """Validate the patch to a quota."""
    return models.QuotaPatch(
        cpu=body.cpu,
        memory=body.memory,
        gpu=body.gpu,
    )


def validate_quota_put(body: apispec.QuotaWithId) -> models.QuotaPatch:
    """Validate the put request for a quota."""
    return models.QuotaPatch(
        cpu=body.cpu,
        memory=body.memory,
        gpu=body.gpu,
    )


def validate_resource_class(body: apispec.ResourceClass) -> models.UnsavedResourceClass:
    """Validate a resource class object."""
    if len(body.name) > 40:
        # TODO: Should this be added to the API spec instead?
        raise errors.ValidationError(message="'name' cannot be longer than 40 characters.")
    if body.default_storage > body.max_storage:
        raise errors.ValidationError(message="The default storage cannot be larger than the max allowable storage.")
    # We need to sort node affinities and tolerations to make '__eq__' reliable
    node_affinities = sorted(
        (
            models.NodeAffinity(key=na.key, required_during_scheduling=na.required_during_scheduling)
            for na in body.node_affinities or []
        ),
        key=lambda x: (x.key, x.required_during_scheduling),
    )
    tolerations = sorted(t.root for t in body.tolerations or [])
    return models.UnsavedResourceClass(
        name=body.name,
        cpu=body.cpu,
        memory=body.memory,
        max_storage=body.max_storage,
        gpu=body.gpu,
        default=body.default,
        default_storage=body.default_storage,
        node_affinities=node_affinities,
        tolerations=tolerations,
    )


@overload
def validate_resource_class_patch(body: apispec.ResourceClassPatch) -> models.ResourceClassPatch: ...
@overload
def validate_resource_class_patch(body: apispec.ResourceClassPatchWithId) -> models.ResourceClassPatchWithId: ...
def validate_resource_class_patch(
    body: apispec.ResourceClassPatch | apispec.ResourceClassPatchWithId,
) -> models.ResourceClassPatch | models.ResourceClassPatchWithId:
    """Validate the patch to a resource class."""
    rc_id = body.id if isinstance(body, apispec.ResourceClassPatchWithId) else None
    node_affinities = None
    if body.node_affinities:
        node_affinities = sorted(
            (
                models.NodeAffinity(key=na.key, required_during_scheduling=na.required_during_scheduling)
                for na in body.node_affinities or []
            ),
            key=lambda x: (x.key, x.required_during_scheduling),
        )
    tolerations = None
    if body.tolerations:
        tolerations = sorted(t.root for t in body.tolerations or [])
    if rc_id:
        return models.ResourceClassPatchWithId(
            id=rc_id,
            name=body.name,
            cpu=body.cpu,
            memory=body.memory,
            max_storage=body.max_storage,
            gpu=body.gpu,
            default=body.default,
            default_storage=body.default_storage,
            node_affinities=node_affinities,
            tolerations=tolerations,
        )
    return models.ResourceClassPatch(
        name=body.name,
        cpu=body.cpu,
        memory=body.memory,
        max_storage=body.max_storage,
        gpu=body.gpu,
        default=body.default,
        default_storage=body.default_storage,
        node_affinities=node_affinities,
        tolerations=tolerations,
    )


@overload
def validate_resource_class_put(body: apispec.ResourceClass) -> models.ResourceClassPatch: ...
@overload
def validate_resource_class_put(body: apispec.ResourceClassWithId) -> models.ResourceClassPatchWithId: ...
def validate_resource_class_put(
    body: apispec.ResourceClass | apispec.ResourceClassWithId,
) -> models.ResourceClassPatch | models.ResourceClassPatchWithId:
    """Validate the put request for a resource class."""
    rc_id = body.id if isinstance(body, apispec.ResourceClassWithId) else None
    node_affinities = []
    if body.node_affinities:
        node_affinities = sorted(
            (
                models.NodeAffinity(key=na.key, required_during_scheduling=na.required_during_scheduling)
                for na in body.node_affinities or []
            ),
            key=lambda x: (x.key, x.required_during_scheduling),
        )
    tolerations = []
    if body.tolerations:
        tolerations = sorted(t.root for t in body.tolerations or [])
    if rc_id:
        return models.ResourceClassPatchWithId(
            id=rc_id,
            name=body.name,
            cpu=body.cpu,
            memory=body.memory,
            max_storage=body.max_storage,
            gpu=body.gpu,
            default=body.default,
            default_storage=body.default_storage,
            node_affinities=node_affinities,
            tolerations=tolerations,
        )
    return models.ResourceClassPatch(
        name=body.name,
        cpu=body.cpu,
        memory=body.memory,
        max_storage=body.max_storage,
        gpu=body.gpu,
        default=body.default,
        default_storage=body.default_storage,
        node_affinities=node_affinities,
        tolerations=tolerations,
    )


def validate_resource_class_update(
    existing: models.ResourceClass, update: models.ResourceClassPatch | models.ResourceClassPatchWithId
) -> None:
    """Validate the update to a resource class."""
    name = update.name if update.name is not None else existing.name
    max_storage = update.max_storage if update.max_storage is not None else existing.max_storage
    default_storage = update.default_storage if update.default_storage is not None else existing.default_storage

    if len(name) > 40:
        # TODO: Should this be added to the API spec instead?
        raise errors.ValidationError(message="'name' cannot be longer than 40 characters.")
    if default_storage > max_storage:
        raise errors.ValidationError(message="The default storage cannot be larger than the max allowable storage.")


def validate_resource_pool(body: apispec.ResourcePool) -> models.UnsavedResourcePool:
    """Validate a resource pool object."""
    if len(body.name) > 40:
        # TODO: Should this be added to the API spec instead?
        raise errors.ValidationError(message="'name' cannot be longer than 40 characters.")
    if body.default and not body.public:
        raise errors.ValidationError(message="The default resource pool has to be public.")
    if body.default and body.quota is not None:
        raise errors.ValidationError(message="A default resource pool cannot have a quota.")
    if body.remote and body.default:
        raise errors.ValidationError(message="The default resource pool cannot start remote sessions.")
    if body.remote and body.public:
        raise errors.ValidationError(message="A resource pool which starts remote sessions cannot be public.")
    if (body.idle_threshold and body.idle_threshold < 0) or (
        body.hibernation_threshold and body.hibernation_threshold < 0
    ):
        raise errors.ValidationError(message="Idle threshold and hibernation threshold need to be larger than 0.")

    idle_threshold = body.idle_threshold
    if idle_threshold == 0:
        idle_threshold = None
    hibernation_threshold = body.hibernation_threshold
    if hibernation_threshold == 0:
        hibernation_threshold = None

    quota = validate_quota(body=body.quota) if body.quota else None
    classes = [validate_resource_class(body=new_cls) for new_cls in body.classes]

    default_classes: list[models.UnsavedResourceClass] = []
    for cls in classes:
        if quota is not None and not quota.is_resource_class_compatible(cls):
            raise errors.ValidationError(
                message=f"The resource class with name {cls.name} is not compatible with the quota."
            )
        if cls.default:
            default_classes.append(cls)
    if len(default_classes) != 1:
        raise errors.ValidationError(message="One default class is required in each resource pool.")

    remote = validate_remote(body=body.remote) if body.remote else None

    return models.UnsavedResourcePool(
        name=body.name,
        classes=classes,
        quota=quota,
        idle_threshold=idle_threshold,
        hibernation_threshold=hibernation_threshold,
        default=body.default,
        public=body.public,
        remote=remote,
        cluster_id=ULID.from_str(body.cluster_id) if body.cluster_id else None,
    )


def validate_resource_pool_patch(body: apispec.ResourcePoolPatch) -> models.ResourcePoolPatch:
    """Validate the patch to a resource pool."""
    classes = [validate_resource_class_patch(body=rc) for rc in body.classes] if body.classes else None
    quota = validate_quota_patch(body=body.quota) if body.quota else None
    remote = validate_remote_patch(body=body.remote) if body.remote else None
    return models.ResourcePoolPatch(
        name=body.name,
        classes=classes,
        quota=quota,
        idle_threshold=body.idle_threshold,
        hibernation_threshold=body.hibernation_threshold,
        default=body.default,
        public=body.public,
        remote=remote,
        cluster_id=ULID.from_str(body.cluster_id) if body.cluster_id else None,
    )


def validate_resource_pool_put(body: apispec.ResourcePoolPut) -> models.ResourcePoolPatch:
    """Validate the put request for a resource pool."""
    # NOTE: the current behavior is to do a PATCH-style update on nested classes for "PUT resource pool"
    classes = [validate_resource_class_put(body=rc) for rc in body.classes] if body.classes else None
    quota = validate_quota_put(body=body.quota) if body.quota else RESET
    remote = validate_remote_put(body=body.remote)
    return models.ResourcePoolPatch(
        name=body.name,
        classes=classes,
        quota=quota,
        idle_threshold=body.idle_threshold,
        hibernation_threshold=body.hibernation_threshold,
        default=body.default,
        public=body.public,
        remote=remote,
        cluster_id=ULID.from_str(body.cluster_id) if body.cluster_id else RESET,
    )


def validate_resource_pool_update(existing: models.ResourcePool, update: models.ResourcePoolPatch) -> None:
    """Validate the update to a resource pool."""
    name = update.name if update.name is not None else existing.name
    classes = existing.classes
    for rc in update.classes or []:
        found = next(filter(lambda tup: tup[1].id == rc.id, enumerate(classes)), None)
        if found is None:
            raise errors.ValidationError(
                message=f"Resource class '{rc.id}' does not exist in resource pool '{existing.id}'."
            )
        idx, existing_rc = found
        classes[idx] = models.ResourceClass(
            name=rc.name if rc.name is not None else existing_rc.name,
            cpu=rc.cpu if rc.cpu is not None else existing_rc.cpu,
            memory=rc.memory if rc.memory is not None else existing_rc.memory,
            max_storage=rc.max_storage if rc.max_storage is not None else existing_rc.max_storage,
            gpu=rc.gpu if rc.gpu is not None else existing_rc.gpu,
            id=existing_rc.id,
            default=rc.default if rc.default is not None else existing_rc.default,
            default_storage=rc.default_storage if rc.default_storage is not None else existing_rc.default_storage,
            node_affinities=rc.node_affinities if rc.node_affinities is not None else existing_rc.node_affinities,
            tolerations=rc.tolerations if rc.tolerations is not None else existing_rc.tolerations,
        )
    quota: models.Quota | models.UnsavedQuota | ResetType = existing.quota if existing.quota else RESET
    if update.quota is RESET:
        quota = RESET
    elif isinstance(update.quota, models.QuotaPatch) and existing.quota is None:
        # The quota patch needs to contain all required fields
        cpu = update.quota.cpu
        if cpu is None:
            raise errors.ValidationError(message="The 'quota.cpu' field is required when creating a new quota.")
        memory = update.quota.memory
        if memory is None:
            raise errors.ValidationError(message="The 'quota.memory' field is required when creating a new quota.")
        gpu = update.quota.gpu
        if gpu is None:
            raise errors.ValidationError(message="The 'quota.gpu' field is required when creating a new quota.")
        quota = models.UnsavedQuota(
            cpu=cpu,
            memory=memory,
            gpu=gpu,
        )
    elif isinstance(update.quota, models.QuotaPatch):
        assert existing.quota is not None
        quota = models.Quota(
            cpu=update.quota.cpu if update.quota.cpu is not None else existing.quota.cpu,
            memory=update.quota.memory if update.quota.memory is not None else existing.quota.memory,
            gpu=update.quota.gpu if update.quota.gpu is not None else existing.quota.gpu,
            gpu_kind=update.quota.gpu_kind if update.quota.gpu_kind is not None else existing.quota.gpu_kind,
            id=existing.quota.id,
        )
    idle_threshold = update.idle_threshold if update.idle_threshold is not None else existing.idle_threshold
    hibernation_threshold = (
        update.hibernation_threshold if update.hibernation_threshold is not None else existing.hibernation_threshold
    )
    default = update.default if update.default is not None else existing.default
    public = update.public if update.public is not None else existing.public
    remote: models.RemoteConfigurationFirecrest | ResetType = existing.remote if existing.remote else RESET
    if update.remote is RESET:
        remote = RESET
    elif isinstance(update.remote, models.RemoteConfigurationFirecrestPatch) and existing.remote is None:
        # The remote patch needs to contain all required fields
        kind = update.remote.kind
        if kind is None:
            raise errors.ValidationError(message="The 'remote.kind' field is required when creating a new remote.")
        api_url = update.remote.api_url
        if api_url is None:
            raise errors.ValidationError(message="The 'remote.api_url' field is required when creating a new remote.")
        system_name = update.remote.system_name
        if system_name is None:
            raise errors.ValidationError(
                message="The 'remote.system_name' field is required when creating a new remote."
            )
        remote = models.RemoteConfigurationFirecrest(
            kind=kind,
            provider_id=update.remote.provider_id,
            api_url=api_url,
            system_name=system_name,
            partition=update.remote.partition,
        )
    elif isinstance(update.remote, models.RemoteConfigurationFirecrestPatch):
        assert existing.remote is not None
        remote = models.RemoteConfigurationFirecrest(
            kind=update.remote.kind if update.remote.kind is not None else existing.remote.kind,
            provider_id=update.remote.provider_id
            if update.remote.provider_id is not None
            else existing.remote.provider_id,
            api_url=update.remote.api_url if update.remote.api_url is not None else existing.remote.api_url,
            system_name=update.remote.system_name
            if update.remote.system_name is not None
            else existing.remote.system_name,
            partition=update.remote.partition if update.remote.partition is not None else existing.remote.partition,
        )

    if len(name) > 40:
        # TODO: Should this be added to the API spec instead?
        raise errors.ValidationError(message="'name' cannot be longer than 40 characters.")
    if default and not public:
        raise errors.ValidationError(message="The default resource pool has to be public.")
    if default and quota is not RESET:
        raise errors.ValidationError(message="A default resource pool cannot have a quota.")
    if isinstance(remote, models.RemoteConfigurationFirecrest) and default:
        raise errors.ValidationError(message="The default resource pool cannot start remote sessions.")
    if isinstance(remote, models.RemoteConfigurationFirecrest) and public:
        raise errors.ValidationError(message="A resource pool which starts remote sessions cannot be public.")
    if (idle_threshold and idle_threshold < 0) or (hibernation_threshold and hibernation_threshold < 0):
        raise errors.ValidationError(message="Idle threshold and hibernation threshold need to be larger than 0.")

    default_classes: list[models.ResourceClass] = []
    for cls in classes:
        if (
            isinstance(quota, models.Quota)
            or isinstance(quota, models.UnsavedQuota)
            and not quota.is_resource_class_compatible(cls)
        ):
            raise errors.ValidationError(
                message=f"The resource class with name {cls.name} is not compatible with the quota."
            )
        if cls.default:
            default_classes.append(cls)
    if len(default_classes) != 1:
        raise errors.ValidationError(message="One default class is required in each resource pool.")


def validate_cluster(body: apispec.Cluster) -> models.ClusterSettings:
    """Convert a REST API Cluster object to a model Cluster object."""
    return models.ClusterSettings(
        name=body.name,
        config_name=body.config_name,
        session_protocol=models.SessionProtocol(body.session_protocol.value),
        session_host=body.session_host,
        session_port=body.session_port,
        session_path=body.session_path,
        session_ingress_class_name=body.session_ingress_class_name,
        session_ingress_annotations=body.session_ingress_annotations.model_dump(),
        session_tls_secret_name=body.session_tls_secret_name,
        session_storage_class=body.session_storage_class,
        service_account_name=body.service_account_name,
    )


def validate_cluster_patch(patch: apispec.ClusterPatch) -> models.ClusterPatch:
    """Convert a REST API Cluster object patch to a model Cluster object."""

    return models.ClusterPatch(
        name=patch.name,
        config_name=patch.config_name,
        session_protocol=models.SessionProtocol(patch.session_protocol.value)
        if patch.session_protocol is not None
        else None,
        session_host=patch.session_host,
        session_port=patch.session_port,
        session_path=patch.session_path,
        session_ingress_class_name=patch.session_ingress_class_name,
        session_ingress_annotations=patch.session_ingress_annotations.model_dump()
        if patch.session_ingress_annotations is not None
        else None,
        session_tls_secret_name=patch.session_tls_secret_name,
        session_storage_class=patch.session_storage_class,
        service_account_name=patch.service_account_name,
    )


def validate_remote(body: apispec.RemoteConfigurationFirecrest) -> models.RemoteConfigurationFirecrest:
    """Validate a remote configuration object."""
    kind = models.RemoteConfigurationKind(body.kind.value)
    if kind != models.RemoteConfigurationKind.firecrest:
        raise errors.ValidationError(message=f"The kind '{kind}' of remote configuration is not supported.", quiet=True)
    validate_firecrest_api_url(body.api_url)
    return models.RemoteConfigurationFirecrest(
        kind=kind,
        provider_id=body.provider_id,
        api_url=body.api_url,
        system_name=body.system_name,
        partition=body.partition,
    )


def validate_remote_put(
    body: apispec.RemoteConfigurationFirecrest | None,
) -> models.RemoteConfigurationPatch:
    """Validate the PUT update to a remote configuration object."""
    if body is None:
        return RESET
    remote = validate_remote(body=body)
    return models.RemoteConfigurationFirecrestPatch(
        kind=remote.kind,
        provider_id=remote.provider_id,
        api_url=remote.api_url,
        system_name=remote.system_name,
        partition=remote.partition,
    )


def validate_remote_patch(
    body: apispec.RemoteConfigurationPatchReset | apispec.RemoteConfigurationFirecrestPatch,
) -> models.RemoteConfigurationPatch:
    """Validate the patch to a remote configuration object."""
    if isinstance(body, apispec.RemoteConfigurationPatchReset):
        return RESET
    kind = models.RemoteConfigurationKind(body.kind.value) if body.kind else None
    if kind and kind != models.RemoteConfigurationKind.firecrest:
        raise errors.ValidationError(message=f"The kind '{kind}' of remote configuration is not supported.", quiet=True)
    if body.api_url:
        validate_firecrest_api_url(body.api_url)
    return models.RemoteConfigurationFirecrestPatch(
        kind=kind,
        provider_id=body.provider_id,
        api_url=body.api_url,
        system_name=body.system_name,
        partition=body.partition,
    )


def validate_firecrest_api_url(url: str) -> None:
    """Validate the URL to the FirecREST API."""
    parsed = urlparse(url)
    if not parsed.netloc:
        raise errors.ValidationError(
            message=f"The host for the firecrest api url {url} is not valid, expected a non-empty value.",
            quiet=True,
        )
    accepted_schemes = ["https"]
    if parsed.scheme not in accepted_schemes:
        raise errors.ValidationError(
            message=f"The scheme for the firecrest api url {url} is not valid, expected one of {accepted_schemes}",
            quiet=True,
        )
