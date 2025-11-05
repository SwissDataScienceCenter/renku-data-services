"""Utilities for notebooks."""

import renku_data_services.crc.models as crc_models
from renku_data_services.base_models.core import RESET, ResetType
from renku_data_services.errors import errors
from renku_data_services.notebooks.crs import (
    Affinity,
    AffinityPatch,
    MatchExpression,
    NodeAffinity,
    NodeAffinityPatch,
    NodeSelectorTerm,
    PodAffinityPatch,
    PodAntiAffinityPatch,
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

    # node_affinity1 and node_affinity2 have nodeSelectorTerms, we preform a cross product
    if (
        node_affinity1.requiredDuringSchedulingIgnoredDuringExecution
        and node_affinity1.requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms
    ) and (
        node_affinity2.requiredDuringSchedulingIgnoredDuringExecution
        and node_affinity2.requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms
    ):
        terms_1 = [*node_affinity1.requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms]
        terms_2 = [*node_affinity2.requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms]
        terms_out: list[NodeSelectorTerm] = []
        for term_1 in terms_1:
            for term_2 in terms_2:
                term_out = NodeSelectorTerm()
                matchExpressions = [*(term_1.matchExpressions or []), *(term_2.matchExpressions or [])]
                if matchExpressions:
                    term_out.matchExpressions = matchExpressions
                matchFields = [*(term_1.matchFields or []), *(term_2.matchFields or [])]
                if matchFields:
                    term_out.matchFields = matchFields
                if term_out.matchExpressions or term_out.matchFields:
                    terms_out.append(term_out)
        if terms_out:
            output.requiredDuringSchedulingIgnoredDuringExecution = RequiredDuringSchedulingIgnoredDuringExecution(
                nodeSelectorTerms=terms_out
            )
    # only node_affinity1 has nodeSelectorTerms, we pick them unchanged
    elif (
        node_affinity1.requiredDuringSchedulingIgnoredDuringExecution
        and node_affinity1.requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms
    ):
        terms_1 = [*node_affinity1.requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms]
        if terms_1:
            output.requiredDuringSchedulingIgnoredDuringExecution = RequiredDuringSchedulingIgnoredDuringExecution(
                nodeSelectorTerms=terms_1
            )
    # only node_affinity2 has nodeSelectorTerms, we pick them unchanged
    elif (
        node_affinity2.requiredDuringSchedulingIgnoredDuringExecution
        and node_affinity2.requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms
    ):
        terms_2 = [*node_affinity2.requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms]
        if terms_2:
            output.requiredDuringSchedulingIgnoredDuringExecution = RequiredDuringSchedulingIgnoredDuringExecution(
                nodeSelectorTerms=terms_2
            )

    return output


def node_affinity_from_resource_class(
    resource_class: crc_models.ResourceClass,
    default_affinity: Affinity | None,
) -> Affinity | None:
    """Generate an affinity from the affinities stored in a resource class."""
    rc_node_affinity: NodeAffinity | None = None
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
        rc_node_affinity = NodeAffinity()
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
        if not rc_node_affinity:
            rc_node_affinity = NodeAffinity()
        rc_node_affinity.preferredDuringSchedulingIgnoredDuringExecution = [
            PreferredDuringSchedulingIgnoredDuringExecutionItem(
                weight=1,
                preference=Preference(
                    # NOTE: matchExpression terms are ANDed by kubernetes
                    matchExpressions=preferred_expr,
                ),
            )
        ]

    match (default_affinity, rc_node_affinity):
        case (None, None):
            return None
        case (None, NodeAffinity()):
            return Affinity(nodeAffinity=rc_node_affinity)
        case (Affinity(), None):
            return default_affinity
        case (Affinity(), NodeAffinity()):
            affinity = default_affinity.model_copy(deep=True)
            if affinity.nodeAffinity:
                affinity.nodeAffinity = intersect_node_affinities(affinity.nodeAffinity, rc_node_affinity)
            else:
                affinity.nodeAffinity = rc_node_affinity
            return affinity
        case _:
            raise errors.ProgrammingError(message="Cannot derive node affinity from resource class and defaults.")


def node_affinity_patch_from_resource_class(
    resource_class: crc_models.ResourceClass, default_affinity: Affinity | None
) -> AffinityPatch | ResetType:
    """Create a patch for the session affinity."""
    affinity = node_affinity_from_resource_class(resource_class, default_affinity)
    if not affinity:
        return RESET
    patch = AffinityPatch(nodeAffinity=RESET, podAffinity=RESET, podAntiAffinity=RESET)
    if affinity.nodeAffinity:
        patch.nodeAffinity = NodeAffinityPatch(
            preferredDuringSchedulingIgnoredDuringExecution=(
                affinity.nodeAffinity.preferredDuringSchedulingIgnoredDuringExecution or RESET
            ),
            requiredDuringSchedulingIgnoredDuringExecution=(
                affinity.nodeAffinity.requiredDuringSchedulingIgnoredDuringExecution or RESET
            ),
        )
    if affinity.podAffinity:
        patch.podAffinity = PodAffinityPatch(
            preferredDuringSchedulingIgnoredDuringExecution=(
                affinity.podAffinity.preferredDuringSchedulingIgnoredDuringExecution or RESET
            ),
            requiredDuringSchedulingIgnoredDuringExecution=(
                affinity.podAffinity.requiredDuringSchedulingIgnoredDuringExecution or RESET
            ),
        )
    if affinity.podAntiAffinity:
        patch.podAntiAffinity = PodAntiAffinityPatch(
            preferredDuringSchedulingIgnoredDuringExecution=(
                affinity.podAntiAffinity.preferredDuringSchedulingIgnoredDuringExecution or RESET
            ),
            requiredDuringSchedulingIgnoredDuringExecution=(
                affinity.podAntiAffinity.requiredDuringSchedulingIgnoredDuringExecution or RESET
            ),
        )
    return patch


def tolerations_from_resource_class(
    resource_class: crc_models.ResourceClass, default_tolerations: list[Toleration]
) -> list[Toleration]:
    """Generate tolerations from the list of tolerations of a resource class."""
    output: list[Toleration] = []
    output.extend(default_tolerations)
    for tol in resource_class.tolerations:
        output.append(Toleration(key=tol, operator="Exists"))
    return output
