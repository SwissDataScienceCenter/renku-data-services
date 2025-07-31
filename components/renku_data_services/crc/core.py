"""crc modules converters and validators."""

from renku_data_services.crc import apispec, models


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
