"""crc modules converters and validators."""

from urllib.parse import urlparse

from renku_data_services.crc import apispec, models
from renku_data_services.errors import errors


def validate_cluster(body: apispec.Cluster) -> models.ClusterSettings:
    """Convert a REST API Cluster object to a model Cluster object."""
    return models.ClusterSettings(
        name=body.name,
        config_name=body.config_name,
        session_protocol=models.SessionProtocol(body.session_protocol.value),
        session_host=body.session_host,
        session_port=body.session_port,
        session_path=body.session_path,
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
        session_ingress_annotations=patch.session_ingress_annotations.model_dump()
        if patch.session_ingress_annotations is not None
        else None,
        session_tls_secret_name=patch.session_tls_secret_name,
        session_storage_class=patch.session_storage_class,
        service_account_name=patch.service_account_name,
    )


def validate_remote_configuration(body: apispec.RemoteConfigurationFirecrest) -> models.RemoteConfigurationFirecrest:
    """Validate a remote configuration object."""
    kind = models.RemoteConfigurationKind(body.kind.value)
    if kind != models.RemoteConfigurationKind.firecrest:
        raise errors.ValidationError(message=f"The kind '{kind}' of remote configuration is not supported.", quiet=True)
    validate_firecrest_api_url(body.api_url)
    return models.RemoteConfigurationFirecrest(
        kind=kind,
        api_url=body.api_url,
        system_name=body.system_name,
        partition=body.partition,
    )


def validate_remote_configuration_patch(
    body: apispec.RemoteConfigurationFirecrestPatch,
) -> models.RemoteConfigurationFirecrestPatch:
    """Validate a remote configuration object."""
    kind = models.RemoteConfigurationKind(body.kind.value) if body.kind else None
    if kind and kind != models.RemoteConfigurationKind.firecrest:
        raise errors.ValidationError(message=f"The kind '{kind}' of remote configuration is not supported.", quiet=True)
    if body.api_url:
        validate_firecrest_api_url(body.api_url)
    return models.RemoteConfigurationFirecrestPatch(
        kind=kind,
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
            message=f"The scheme for the image registry url {url} is not valid, expected one of {accepted_schemes}",
            quiet=True,
        )
