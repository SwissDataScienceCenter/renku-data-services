"""crc modules converters and validators."""

from renku_data_services.crc import apispec, models


def validate_cluster(body: apispec.Cluster) -> models.Cluster:
    """Convert a REST API Cluster object to a model Cluster object."""
    return models.Cluster(
        name=body.name,
        config_name=body.config_name,
        session_protocol=body.session_protocol,
        session_host=body.session_host,
        session_port=body.session_port,
        session_path=body.session_path,
        session_ingress_annotations=body.session_ingress_annotations.model_dump(),
        session_tls_secret_name=body.session_tls_secret_name,
        session_storage_class=body.session_storage_class,
    )


def validate_cluster_patch(patch: apispec.ClusterPatch) -> models.ClusterPatch:
    """Convert a REST API Cluster object patch to a model Cluster object."""

    if (s := patch.session_storage_class) is not None and s == "":
        # If we received an empty string in the storage class, reset it to the default storage class by setting
        # it to None.
        patch.session_storage_class = None

    return models.ClusterPatch(
        name=patch.name,
        config_name=patch.config_name,
        session_protocol=patch.session_protocol,
        session_host=patch.session_host,
        session_port=patch.session_port,
        session_path=patch.session_path,
        session_ingress_annotations=patch.session_ingress_annotations.model_dump()
        if patch.session_ingress_annotations is not None
        else None,
        session_tls_secret_name=patch.session_tls_secret_name,
        session_storage_class=patch.session_storage_class,
    )
