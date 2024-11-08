"""Utilities for notebooks."""

import httpx

import renku_data_services.crc.models as crc_models
from renku_data_services.base_models.core import AuthenticatedAPIUser
from renku_data_services.notebooks.crs import (
    MatchExpression,
    NodeAffinity,
    NodeSelectorTerm,
    Preference,
    PreferredDuringSchedulingIgnoredDuringExecutionItem,
    RequiredDuringSchedulingIgnoredDuringExecution,
    Toleration,
)
from renku_data_services.utils.cryptography import get_encryption_key


def merge_node_affinities(
    node_affinity1: NodeAffinity,
    node_affinity2: NodeAffinity,
) -> NodeAffinity:
    """Merge two node affinities into a brand new object."""
    output = NodeAffinity()
    if node_affinity1.preferredDuringSchedulingIgnoredDuringExecution:
        output.preferredDuringSchedulingIgnoredDuringExecution = (
            node_affinity1.preferredDuringSchedulingIgnoredDuringExecution
        )
    if node_affinity2.preferredDuringSchedulingIgnoredDuringExecution:
        if output.preferredDuringSchedulingIgnoredDuringExecution:
            output.preferredDuringSchedulingIgnoredDuringExecution.extend(
                node_affinity2.preferredDuringSchedulingIgnoredDuringExecution
            )
        else:
            output.preferredDuringSchedulingIgnoredDuringExecution = (
                node_affinity2.preferredDuringSchedulingIgnoredDuringExecution
            )
    if (
        node_affinity1.requiredDuringSchedulingIgnoredDuringExecution
        and node_affinity1.requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms
    ):
        output.requiredDuringSchedulingIgnoredDuringExecution = RequiredDuringSchedulingIgnoredDuringExecution(
            nodeSelectorTerms=node_affinity1.requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms
        )
    if (
        node_affinity2.requiredDuringSchedulingIgnoredDuringExecution
        and node_affinity2.requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms
    ):
        if output.requiredDuringSchedulingIgnoredDuringExecution:
            output.requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms.extend(
                node_affinity2.requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms
            )
        else:
            output.requiredDuringSchedulingIgnoredDuringExecution = RequiredDuringSchedulingIgnoredDuringExecution(
                nodeSelectorTerms=(node_affinity2.requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms)
            )
    return output


def node_affinity_from_resource_class(resource_class: crc_models.ResourceClass) -> NodeAffinity:
    """Generate an affinity from the affinities stored in a resource class."""
    output = NodeAffinity()
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
        output.requiredDuringSchedulingIgnoredDuringExecution = RequiredDuringSchedulingIgnoredDuringExecution(
            nodeSelectorTerms=[
                # NOTE: Node selector terms are ORed by kubernetes
                NodeSelectorTerm(
                    # NOTE: matchExpression terms are ANDed by kubernetes
                    matchExpressions=required_expr,
                )
            ]
        )
    if preferred_expr:
        output.preferredDuringSchedulingIgnoredDuringExecution = [
            PreferredDuringSchedulingIgnoredDuringExecutionItem(
                weight=1,
                preference=Preference(
                    # NOTE: matchExpression terms are ANDed by kubernetes
                    matchExpressions=preferred_expr,
                ),
            )
        ]
    return output


def tolerations_from_resource_class(resource_class: crc_models.ResourceClass) -> list[Toleration]:
    """Generate tolerations from the list of tolerations of a resource class."""
    output: list[Toleration] = []
    for tol in resource_class.tolerations:
        output.append(Toleration(key=tol, operator="Exists"))
    return output


async def get_user_secret(data_svc_url: str, user: AuthenticatedAPIUser) -> str | None:
    """Get the user secret key from the secret service."""

    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(
            f"{data_svc_url}/user/secret_key",
            headers={"Authorization": f"Bearer {user.access_token}"},
        )
        if response.status_code != 200:
            return None
        user_key = response.json()

        return get_encryption_key(user_key["secret_key"].encode(), user.id.encode()).decode("utf-8")
