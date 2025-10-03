"""Utilities for notebooks."""

import renku_data_services.crc.models as crc_models
from renku_data_services.notebooks.crs import (
    Affinity,
    MatchExpression,
    NodeAffinity,
    NodeSelectorTerm,
    Preference,
    PreferredDuringSchedulingIgnoredDuringExecutionItem,
    RequiredDuringSchedulingIgnoredDuringExecution,
    Toleration,
)


def intersect_node_affinities(
    node_affinity1: NodeAffinity,
    node_affinity2: NodeAffinity,
) -> NodeAffinity:
    """Merge two node affinities into a brand new object."""
    output = NodeAffinity()

    if (
        node_affinity1.preferredDuringSchedulingIgnoredDuringExecution
        or node_affinity2.preferredDuringSchedulingIgnoredDuringExecution
    ):
        items = [
            *(node_affinity1.preferredDuringSchedulingIgnoredDuringExecution or []),
            *(node_affinity2.preferredDuringSchedulingIgnoredDuringExecution or []),
        ]
        if items:
            output.preferredDuringSchedulingIgnoredDuringExecution = items

    if (
        node_affinity1.requiredDuringSchedulingIgnoredDuringExecution
        and node_affinity1.requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms
    ):
        output.requiredDuringSchedulingIgnoredDuringExecution = (
            node_affinity1.requiredDuringSchedulingIgnoredDuringExecution.model_copy()
        )
        if (
            node_affinity2.requiredDuringSchedulingIgnoredDuringExecution
            and node_affinity2.requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms
        ):
            for term_out in output.requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms:
                for term_2 in node_affinity2.requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms:
                    matchExpressions = [
                        *(term_out.matchExpressions or []),
                        *(term_2.matchExpressions or []),
                    ]
                    if matchExpressions:
                        term_out.matchExpressions = matchExpressions
                    matchFields = [
                        *(term_out.matchFields or []),
                        *(term_2.matchFields or []),
                    ]
                    if matchFields:
                        term_out.matchFields = matchFields

    return output


def node_affinity_from_resource_class(
    resource_class: crc_models.ResourceClass,
    default_affinity: Affinity,
) -> Affinity:
    """Generate an affinity from the affinities stored in a resource class."""
    rc_node_affinity = NodeAffinity()
    required_expr = [
        MatchExpression(key=affinity.key, operator="Exists")
        for affinity in resource_class.node_affinities
        if affinity.required_during_scheduling
    ]
    preferred_expr = [
        MatchExpression(key=affinity.key, operator="Exists")
        for affinity in resource_class.node_affinities
        if not affinity.required_during_scheduling
    ]
    if required_expr:
        rc_node_affinity.requiredDuringSchedulingIgnoredDuringExecution = (
            RequiredDuringSchedulingIgnoredDuringExecution(
                nodeSelectorTerms=[
                    # NOTE: Node selector terms are ORed by kubernetes
                    NodeSelectorTerm(
                        # NOTE: matchExpression terms are ANDed by kubernetes
                        matchExpressions=required_expr,
                    )
                ]
            )
        )
    if preferred_expr:
        rc_node_affinity.preferredDuringSchedulingIgnoredDuringExecution = [
            PreferredDuringSchedulingIgnoredDuringExecutionItem(
                weight=1,
                preference=Preference(
                    # NOTE: matchExpression terms are ANDed by kubernetes
                    matchExpressions=preferred_expr,
                ),
            )
        ]

    affinity = default_affinity.model_copy(deep=True)
    if affinity.nodeAffinity:
        affinity.nodeAffinity = intersect_node_affinities(affinity.nodeAffinity, rc_node_affinity)
    else:
        affinity.nodeAffinity = rc_node_affinity
    return affinity


def tolerations_from_resource_class(
    resource_class: crc_models.ResourceClass, default_tolerations: list[Toleration]
) -> list[Toleration]:
    """Generate tolerations from the list of tolerations of a resource class."""
    output: list[Toleration] = []
    output.extend(default_tolerations)
    for tol in resource_class.tolerations:
        output.append(Toleration(key=tol, operator="Exists"))
    return output
