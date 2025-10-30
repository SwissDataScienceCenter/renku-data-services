"""Models for internal logic."""

from dataclasses import dataclass
from enum import StrEnum


class NodeSelectorRequirementOperator(StrEnum):
    """The different types of operator which can be used in NodeSelectorRequirement.

    See: https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.34/#nodeselectorrequirement-v1-core.
    """

    does_not_exist = "DoesNotExist"
    exists = "Exists"
    greater_than = "Gt"
    less_than = "Lt"
    not_in = "NotIn"


@dataclass(frozen=True, eq=True, kw_only=True)
class NodeSelectorRequirement:
    """Node selector requirement.

    A node selector requirement is a selector that contains values, a key,
    and an operator that relates the key and values.

    See: https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.34/#nodeselectorrequirement-v1-core.

    """

    key: str
    """The label key that the selector applies to."""

    operator: NodeSelectorRequirementOperator
    """Represents a key's relationship to a set of values."""

    values: list[str] | None = None
    """An array of string values."""


@dataclass(frozen=True, eq=True, kw_only=True)
class NodeSelectorTerm:
    """Selector term for scheduling pods on nodes.

    See: https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.34/#nodeselectorterm-v1-core.
    """

    matchExpressions: list[NodeSelectorRequirement] | None = None
    """A list of node selector requirements by node's labels."""

    matchFields: list[NodeSelectorRequirement] | None = None
    """A list of node selector requirements by node's fields."""


@dataclass(frozen=True, eq=True, kw_only=True)
class PreferredDuringSchedulingIgnoredDuringExecutionItem:
    """Preference term for scheduling.

    See: https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.34/#preferredschedulingterm-v1-core.
    """

    preference: NodeSelectorTerm
    """A node selector term, associated with the corresponding weight."""

    weight: int
    """Weight associated with matching the corresponding nodeSelectorTerm, in the range 1-100."""


@dataclass(frozen=True, eq=True, kw_only=True)
class NodeSelector:
    """A node selector.

    See: https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.34/#nodeselector-v1-core.
    """

    nodeSelectorTerms: list[NodeSelectorTerm]
    """Required. A list of node selector terms. The terms are ORed."""


@dataclass(frozen=True, eq=True, kw_only=True)
class NodeAffinity:
    """Node affinity field.

    See: https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.34/#nodeaffinity-v1-core.
    """

    preferredDuringSchedulingIgnoredDuringExecution: (
        list[PreferredDuringSchedulingIgnoredDuringExecutionItem] | None
    ) = None
    """The scheduler will prefer to schedule pods to nodes that satisfy the affinity expressions specified
    by this field, but it may choose a node that violates one or more of the expressions.
    The node that is most preferred is the one with the greatest sum of weights,
    i.e. for each node that meets all of the scheduling requirements (resource request,
    requiredDuringScheduling affinity expressions, etc.), compute a sum by iterating through
    the elements of this field and adding "weight" to the sum if the node matches the corresponding matchExpressions;
    the node(s) with the highest sum are the most preferred."""

    requiredDuringSchedulingIgnoredDuringExecution: NodeSelector | None = None
    """If the affinity requirements specified by this field are not met at scheduling time,
    the pod will not be scheduled onto the node.
    If the affinity requirements specified by this field cease to be met at some point
    during pod execution (e.g. due to an update),
    the system may or may not try to eventually evict the pod from its node."""


class LabelSelectorRequirementOperator(StrEnum):
    """The different types of operator which can be used in LabelSelectorRequirement.

    See: https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.34/#labelselectorrequirement-v1-meta.
    """

    does_not_exist = "DoesNotExist"
    exists = "Exists"
    not_in = "NotIn"


@dataclass(frozen=True, eq=True, kw_only=True)
class LabelSelectorRequirement:
    """Label selector requirement.

    A label selector requirement is a selector that contains values, a key,
    and an operator that relates the key and values.

    See: https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.34/#labelselectorrequirement-v1-meta.
    """

    key: str
    """key is the label key that the selector applies to."""

    operator: LabelSelectorRequirementOperator
    """operator represents a key's relationship to a set of values."""

    values: list[str] | None = None
    """values is an array of string values."""


@dataclass(frozen=True, eq=True, kw_only=True)
class LabelSelector:
    """Represents a label selector.

    A label selector is a label query over a set of resources.
    The result of matchLabels and matchExpressions are ANDed.
    An empty label selector matches all objects. A null label selector matches no objects.
    """

    matchExpressions: list[LabelSelectorRequirement] | None = None
    """matchExpressions is a list of label selector requirements. The requirements are ANDed."""

    matchLabels: dict[str, str] | None = None
    """matchLabels is a map of {key,value} pairs.

    A single {key,value} in the matchLabels map is equivalent to an element of matchExpressions,
    whose key field is "key", the operator is "In", and the values array contains only "value".
    The requirements are ANDed.
    """


@dataclass(frozen=True, eq=True, kw_only=True)
class PodAffinityTerm:
    """Pod affinity term.

    Defines a set of pods (namely those matching the labelSelector relative to the given namespace(s))
    that this pod should be co-located (affinity) or not co-located (anti-affinity) with,
    where co-located is defined as running on a node whose value of the label
    with key <topologyKey> matches that of any node on which a pod of the set of pods is running.

    See: https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.34/#podaffinityterm-v1-core.
    """

    labelSelector: LabelSelector | None = None
    """A label query over a set of resources, in this case pods.
    If it's null, this PodAffinityTerm matches with no Pods."""

    matchLabelKeys: list[str] | None = None
    """MatchLabelKeys is a set of pod label keys to select which pods will be taken into consideration.
    The keys are used to lookup values from the incoming pod labels,
    those key-value labels are merged with `labelSelector` as `key in (value)`
    to select the group of existing pods which pods will be taken into consideration
    for the incoming pod's pod (anti) affinity. Keys that don't exist in the incoming pod labels will be ignored.
    The default value is empty. The same key is forbidden to exist in both matchLabelKeys and labelSelector.
    Also, matchLabelKeys cannot be set when labelSelector isn't set."""

    mismatchLabelKeys: list[str] | None = None
    """MismatchLabelKeys is a set of pod label keys to select which pods will be taken into consideration.
    The keys are used to lookup values from the incoming pod labels,
    those key-value labels are merged with `labelSelector` as `key notin (value)`
    to select the group of existing pods which pods will be taken into consideration
    for the incoming pod's pod (anti) affinity. Keys that don't exist in the incoming pod labels will be ignored.
    The default value is empty. The same key is forbidden to exist in both mismatchLabelKeys and labelSelector.
    Also, mismatchLabelKeys cannot be set when labelSelector isn't set."""

    namespaceSelector: LabelSelector | None = None
    """A label query over the set of namespaces that the term applies to.
    The term is applied to the union of the namespaces selected by this field
    and the ones listed in the namespaces field.
    null selector and null or empty namespaces list means "this pod's namespace".
    An empty selector ({}) matches all namespaces."""

    namespaces: list[str] | None = None
    """namespaces specifies a static list of namespace names that the term applies to.
    The term is applied to the union of the namespaces listed in this field
    and the ones selected by namespaceSelector.
    null or empty namespaces list and null namespaceSelector means "this pod's namespace"."""

    topologyKey: str
    """This pod should be co-located (affinity) or not co-located (anti-affinity)
    with the pods matching the labelSelector in the specified namespaces,
    where co-located is defined as running on a node whose value of the label
    with key topologyKey matches that of any node on which any of the selected pods is running.
    Empty topologyKey is not allowed."""


@dataclass(frozen=True, eq=True, kw_only=True)
class WeightedPodAffinityTerm:
    """Weighted pod affinity term.

    The weights of all of the matched WeightedPodAffinityTerm fields are added per-node
    to find the most preferred node(s).
    """

    podAffinityTerm: PodAffinityTerm
    """Required. A pod affinity term, associated with the corresponding weight."""

    weight: int
    """weight associated with matching the corresponding podAffinityTerm, in the range 1-100."""


@dataclass(frozen=True, eq=True, kw_only=True)
class PodAffinity:
    """Pod affinity field.

    See: https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.34/#podaffinity-v1-core.
    """

    preferredDuringSchedulingIgnoredDuringExecution: list[WeightedPodAffinityTerm] | None = None
    """The scheduler will prefer to schedule pods to nodes that satisfy
    the affinity expressions specified by this field,
    but it may choose a node that violates one or more of the expressions.
    The node that is most preferred is the one with the greatest sum of weights,
    i.e. for each node that meets all of the scheduling requirements (resource request,
    requiredDuringScheduling affinity expressions, etc.), compute a sum
    by iterating through the elements of this field and adding "weight" to the sum
    if the node has pods which matches the corresponding podAffinityTerm;
    the node(s) with the highest sum are the most preferred."""

    requiredDuringSchedulingIgnoredDuringExecution: list[PodAffinityTerm] | None = None
    """If the affinity requirements specified by this field are not met at scheduling time,
    the pod will not be scheduled onto the node.
    If the affinity requirements specified by this field cease to be met at some point
    during pod execution (e.g. due to a pod label update),
    the system may or may not try to eventually evict the pod from its node.
    When there are multiple elements, the lists of nodes corresponding to each podAffinityTerm are intersected,
    i.e. all terms must be satisfied."""


@dataclass(frozen=True, eq=True, kw_only=True)
class PodAntiAffinity:
    """Pod anti-affinity field.

    See: https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.34/#podantiaffinity-v1-core.
    """

    preferredDuringSchedulingIgnoredDuringExecution: list[WeightedPodAffinityTerm] | None = None
    """The scheduler will prefer to schedule pods to nodes that satisfy
    the anti-affinity expressions specified by this field,
    but it may choose a node that violates one or more of the expressions.
    The node that is most preferred is the one with the greatest sum of weights,
    i.e. for each node that meets all of the scheduling requirements (resource request,
    requiredDuringScheduling anti-affinity expressions, etc.), compute a sum
    by iterating through the elements of this field and subtracting "weight" from the sum
    if the node has pods which matches the corresponding podAffinityTerm;
    the node(s) with the highest sum are the most preferred."""

    requiredDuringSchedulingIgnoredDuringExecution: list[PodAffinityTerm] | None = None
    """If the anti-affinity requirements specified by this field are not met at scheduling time,
    the pod will not be scheduled onto the node.
    If the anti-affinity requirements specified by this field cease to be met at some point
    during pod execution (e.g. due to a pod label update),
    the system may or may not try to eventually evict the pod from its node.
    When there are multiple elements, the lists of nodes corresponding to each podAffinityTerm are intersected,
    i.e. all terms must be satisfied."""


@dataclass(frozen=True, eq=True, kw_only=True)
class Affinity:
    """Affinity field.

    See: https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.34/#affinity-v1-core.
    """

    nodeAffinity: NodeAffinity | None = None
    """Describes node affinity scheduling rules for the pod."""

    podAffinity: PodAffinity | None = None
    """Describes pod affinity scheduling rules
    (e.g. co-locate this pod in the same node, zone, etc. as some other pod(s))."""

    podAntiAffinity: PodAntiAffinity | None = None
    """Describes pod anti-affinity scheduling rules
    (e.g. avoid putting this pod in the same node, zone, etc. as some other pod(s))."""


class TolerationEffect(StrEnum):
    """The different types of effects of a taint.

    See: https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.34/#toleration-v1-core.
    """

    no_execute = "NoExecute"
    no_schedule = "NoSchedule"
    prefer_no_schedule = "PreferNoSchedule"


class TolerationOperator(StrEnum):
    """The different types of operators of a toleration.

    See: https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.34/#toleration-v1-core.
    """

    equal = "Equal"
    exists = "Exists"


@dataclass(frozen=True, eq=True, kw_only=True)
class Toleration:
    """Toleration term.

    The pod this Toleration is attached to tolerates any taint that matches the triple <key,value,effect>
    using the matching operator <operator>.

    See: https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.34/#toleration-v1-core.
    """

    effect: TolerationEffect | None = None
    """Effect indicates the taint effect to match."""

    key: str | None = None
    """Key is the taint key that the toleration applies to.
    Empty means match all taint keys.
    If the key is empty, operator must be Exists; this combination means to match all values and all keys."""

    operator: TolerationOperator | None = None
    """Operator represents a key's relationship to the value."""

    tolerationSeconds: int | None = None
    """TolerationSeconds represents the period of time the toleration
    (which must be of effect NoExecute, otherwise this field is ignored) tolerates the taint.
    By default, it is not set, which means tolerate the taint forever (do not evict).
    Zero and negative values will be treated as 0 (evict immediately) by the system."""

    value: str | None = None
    """Value is the taint value the toleration matches to.
    If the operator is Exists, the value should be empty, otherwise just a regular string."""


type AffinityField = Affinity | None
"""Affinity field.

See: https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.34/#affinity-v1-core.
"""


type NodeSelectorField = dict[str, str] | None
"""Node selector field.

See: https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.34/#podspec-v1-core.
"""

type TolerationsField = list[Toleration] | None
"""Tolerations field.

See:  https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.34/#podspec-v1-core.
"""
