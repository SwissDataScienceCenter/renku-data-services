"""crc modules converters and validators."""

from dataclasses import asdict

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


def validate_cluster_patch(cluster: models.SavedCluster, body: apispec.ClusterPatch) -> models.Cluster:
    """Convert a REST API Cluster object patch to a model Cluster object."""
    cluster = asdict(cluster)
    cluster.pop("id", None)

    patch = body.model_dump(exclude_none=True)
    return models.Cluster(**{**cluster, **patch})
