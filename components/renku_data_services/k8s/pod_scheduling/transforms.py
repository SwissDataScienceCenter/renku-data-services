"""Functions to transform API models into internal ones."""

from renku_data_services.k8s.pod_scheduling import api, models


def transform_tolerations(body: api.TolerationsField) -> models.TolerationsField:
    """Transforms tolerations."""
    if body.root is None:
        return None
    return [transform_toleration(body=tol) for tol in body.root]


def transform_toleration(body: api.Toleration) -> models.Toleration:
    """Transforms a toleration item."""
    effect = models.TolerationEffect(body.effect) if body.effect else None
    operator = models.TolerationOperator(body.operator) if body.operator else None
    return models.Toleration(
        effect=effect,
        key=body.key,
        operator=operator,
        tolerationSeconds=body.tolerationSeconds,
        value=body.value,
    )
