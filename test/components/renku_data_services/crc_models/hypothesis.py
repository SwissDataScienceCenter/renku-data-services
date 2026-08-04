import re

from hypothesis import assume
from hypothesis import strategies as st

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.crc import apispec, models
from renku_data_services.crc.constants import DEFAULT_RUNTIME_PLATFORM


def make_cpu_float(data: dict[str, int]) -> dict[str, int | float]:
    result: dict[str, int | float] = dict(data)
    if "cpu" in result:
        result["cpu"] = float(result["cpu"])
    return result


SQL_BIGINT_MAX: int = 9_223_372_036_854_775_807
SQL_INT_MAX = 2_147_483_647
# NOTE: A quota always has to have resource that are greater than a class
a_rc_cpu = st.floats(min_value=0.0, max_value=10)
a_rc_gpu = st.integers(min_value=0, max_value=100)
a_rc_storage = st.integers(min_value=1, max_value=1000)
a_rc_memory = st.integers(min_value=0, max_value=32)
a_quota_cpu = st.floats(min_value=50, max_value=100)
a_quota_gpu = st.integers(min_value=200, max_value=1000)
a_quota_storage = st.integers(min_value=2000, max_value=10000)
a_quota_memory = st.integers(min_value=64, max_value=1000)
a_row_id = st.integers(min_value=1, max_value=SQL_BIGINT_MAX)
a_name = st.text(min_size=5, max_size=40, alphabet=st.characters(codec="utf-8", exclude_characters=["\x00"]))
a_uuid_string = st.uuids(version=4).map(lambda x: str(x))
a_bool = st.booleans()
a_tolerations_list = st.lists(a_uuid_string, min_size=3, max_size=3)
a_threshold = st.one_of(st.none(), st.integers(min_value=1, max_value=SQL_INT_MAX))


@st.composite
def node_affinity_strat(draw):
    try:
        return models.NodeAffinity(
            key=draw(a_uuid_string),
            required_during_scheduling=draw(a_bool),
        )
    except errors.ValidationError:
        assume(False)


@st.composite
def rc_non_default_strat(draw):
    try:
        return models.UnsavedResourceClass(
            name=draw(a_name),
            cpu=draw(a_rc_cpu),
            gpu=draw(a_rc_gpu),
            max_storage=draw(a_rc_storage),
            memory=draw(a_rc_memory),
            default=False,
            quota_enforced=draw(a_bool),
            tolerations=draw(a_tolerations_list),
            node_affinities=draw(st.lists(node_affinity_strat(), max_size=3)),
        )
    except errors.ValidationError:
        assume(False)


@st.composite
def rc_default_strat(draw):
    try:
        return models.UnsavedResourceClass(
            name=draw(a_name),
            cpu=draw(a_rc_cpu),
            gpu=draw(a_rc_gpu),
            max_storage=draw(a_rc_storage),
            memory=draw(a_rc_memory),
            default=True,
            quota_enforced=draw(a_bool),
        )
    except errors.ValidationError:
        assume(False)


quota_strat = st.builds(models.UnsavedQuota, cpu=a_quota_cpu, gpu=a_quota_gpu, memory=a_quota_memory)
quota_strat_w_id = st.builds(models.Quota, cpu=a_quota_cpu, gpu=a_quota_gpu, memory=a_quota_memory, id=a_uuid_string)


@st.composite
def rp_strat(draw):
    quota = draw(quota_strat)
    classes = draw(st.lists(rc_non_default_strat(), min_size=1, max_size=5))
    classes.append(draw(rc_default_strat()))
    default = False
    public = draw(a_bool)
    name = draw(a_name)
    idle_threshold = draw(a_threshold)
    hibernation_threshold = draw(a_threshold)
    try:
        return models.UnsavedResourcePool(
            name=name,
            classes=classes,
            quota=quota,
            default=default,
            public=public,
            idle_threshold=idle_threshold,
            hibernation_threshold=hibernation_threshold,
            platform=DEFAULT_RUNTIME_PLATFORM,
        )
    except errors.ValidationError:
        assume(False)


public_rp_strat = rp_strat().filter(lambda x: x.public)
private_rp_strat = rp_strat().filter(lambda x: not x.public)
rp_list_strat = st.lists(rp_strat(), min_size=1, max_size=5)
user_strat = st.builds(base_models.User, keycloak_id=a_uuid_string)
user_list_strat = st.lists(user_strat, max_size=5, min_size=1, unique=True)


rc_update_reqs_dict = st.dictionaries(
    keys=st.sampled_from(["cpu", "gpu", "memory", "max_storage"]),
    # We have to ensure we do not overlap with the base values, or we may draw exactly the same set as in the initial
    # conditions. Keep the range small, for faster tests...
    values=st.integers(min_value=20_000, max_value=20_005),
    min_size=1,
).map(make_cpu_float)

quota_update_reqs_dict = st.dictionaries(
    keys=st.sampled_from(["cpu", "gpu", "memory", "storage"]),
    values=st.integers(min_value=1, max_value=5),
    min_size=1,
).map(make_cpu_float)


# ---------------------------------------------------------------------------
# Strategies for API-spec (crc.apispec) resource class inputs.
# These are used to test the validators in renku_data_services.crc.core.
# ---------------------------------------------------------------------------

a_long_name = st.text(min_size=41, max_size=80, alphabet=st.characters(codec="utf-8", exclude_characters=["\x00"]))
a_k8s_label = st.text(
    min_size=3,
    max_size=10,
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters=("-", "_", ".", "/")),
).filter(lambda x: re.match(r"^[a-z0-9A-Z][a-z0-9A-Z-_./]*[a-z0-9A-Z]$", x))
a_cpu_float = st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False)
a_cpu_int = st.integers(min_value=1, max_value=10)


# Map between apispec.RemoteKind and models.RemoteConfigurationKind
_REMOTE_KIND_MAP = {
    apispec.RemoteKind.local: models.RemoteConfigurationKind.local,
    apispec.RemoteKind.firecrest: models.RemoteConfigurationKind.firecrest,
    apispec.RemoteKind.runai: models.RemoteConfigurationKind.runai,
}


def _to_apispec_kind(kind: models.RemoteConfigurationKind) -> apispec.RemoteKind:
    for apispec_kind, model_kind in _REMOTE_KIND_MAP.items():
        if model_kind == kind:
            return apispec_kind
    raise ValueError(f"Unknown model kind: {kind}")


def _to_model_kind(kind: apispec.RemoteKind) -> models.RemoteConfigurationKind:
    return _REMOTE_KIND_MAP[kind]


@st.composite
def apispec_node_affinity_strat(draw):
    """Generate a valid apispec.NodeAffinity."""
    return apispec.NodeAffinity(
        key=draw(a_k8s_label),
        required_during_scheduling=draw(a_bool),
    )


@st.composite
def apispec_tolerations_strat(draw):
    """Generate a valid list of apispec.K8sLabel values."""
    labels = draw(st.lists(a_k8s_label, min_size=0, max_size=3))
    return [apispec.K8sLabel(root=label) for label in labels]


@st.composite
def apispec_remote_class_configuration_firecrest_strat(draw):
    """Generate a valid apispec.RemoteClassConfigurationFirecrest."""
    return apispec.RemoteClassConfigurationFirecrest(
        system_name=draw(st.one_of(st.none(), a_name)),
        partition=draw(st.one_of(st.none(), a_name)),
    )


@st.composite
def _resource_class_base_kwargs(draw, *, kind: apispec.RemoteKind):
    """Draw the shared fields for an apispec resource class body."""
    cpu = draw(a_cpu_int if kind == apispec.RemoteKind.firecrest else a_cpu_float)
    default_storage = draw(st.integers(min_value=1, max_value=500))
    max_storage = draw(st.integers(min_value=default_storage, max_value=1000))

    return {
        "name": draw(a_name),
        "default": draw(a_bool),
        "cpu": cpu,
        "memory": draw(st.integers(min_value=1, max_value=128)),
        "gpu": draw(st.integers(min_value=0, max_value=8)),
        "max_storage": max_storage,
        "default_storage": default_storage,
        "tolerations": draw(st.one_of(st.none(), apispec_tolerations_strat())),
        "node_affinities": draw(st.one_of(st.none(), st.lists(apispec_node_affinity_strat(), min_size=0, max_size=3))),
        "quota_enforced": draw(a_bool),
    }


@st.composite
def apispec_resource_class_strat(
    draw, *, kind: apispec.RemoteKind | st.SearchStrategy[apispec.RemoteKind] | None = None
):
    """Generate a valid apispec.ResourceClass.

    Pass ``kind`` to fix the remote kind; otherwise one is drawn at random.
    The optional ``remote`` field is only populated for FirecREST kinds because
    the validator rejects it for other kinds.
    """
    resolved_kind = draw(kind) if isinstance(kind, st.SearchStrategy) else kind
    if resolved_kind is None:
        resolved_kind = draw(st.sampled_from(list(apispec.RemoteKind)))

    kwargs = draw(_resource_class_base_kwargs(kind=resolved_kind))
    remote = None
    if resolved_kind == apispec.RemoteKind.firecrest:
        remote = draw(st.one_of(st.none(), apispec_remote_class_configuration_firecrest_strat()))

    return apispec.ResourceClass(kind=resolved_kind, remote=remote, **kwargs)


@st.composite
def apispec_resource_class_mismatch_kind_strat(draw):
    """Generate an apispec.ResourceClass together with a deliberately mismatched pool kind."""
    body_kind = draw(st.sampled_from(list(apispec.RemoteKind)))
    body = draw(apispec_resource_class_strat(kind=body_kind))
    # Pick a pool kind that is guaranteed to differ from the body kind.
    pool_kind_options = [k for k in models.RemoteConfigurationKind if _to_model_kind(body_kind) != k]
    pool_kind = draw(st.sampled_from(pool_kind_options))
    return body, pool_kind


@st.composite
def apispec_resource_class_invalid_strat(
    draw,
    *,
    invalid_case: str | None = None,
):
    """Generate an apispec.ResourceClass that passes pydantic validation but fails core validators."""
    case = invalid_case or draw(
        st.sampled_from(
            [
                "firecrest_fractional_cpu",
                "non_firecrest_with_remote",
                "name_too_long",
                "default_storage_larger_than_max",
            ]
        )
    )

    if case == "firecrest_fractional_cpu":
        kwargs = draw(_resource_class_base_kwargs(kind=apispec.RemoteKind.firecrest))
        kwargs["cpu"] = draw(a_cpu_float)
        return apispec.ResourceClass(kind=apispec.RemoteKind.firecrest, remote=None, **kwargs)

    if case == "non_firecrest_with_remote":
        kind = draw(st.sampled_from([apispec.RemoteKind.local, apispec.RemoteKind.runai]))
        kwargs = draw(_resource_class_base_kwargs(kind=kind))
        remote = draw(apispec_remote_class_configuration_firecrest_strat())
        return apispec.ResourceClass(kind=kind, remote=remote, **kwargs)

    if case == "name_too_long":
        kind = draw(st.sampled_from(list(apispec.RemoteKind)))
        kwargs = draw(_resource_class_base_kwargs(kind=kind))
        kwargs["name"] = draw(a_long_name)
        return apispec.ResourceClass(kind=kind, remote=None, **kwargs)

    # default_storage_larger_than_max
    kind = draw(st.sampled_from(list(apispec.RemoteKind)))
    kwargs = draw(_resource_class_base_kwargs(kind=kind))
    kwargs["default_storage"] = kwargs["max_storage"] + draw(st.integers(min_value=1, max_value=100))
    return apispec.ResourceClass(kind=kind, remote=None, **kwargs)


@st.composite
def apispec_resource_class_patch_strat(
    draw,
    *,
    existing_kind: models.RemoteConfigurationKind | None = None,
):
    """Generate an apispec.ResourceClassPatch relative to an existing resource class kind."""
    include_kind = draw(a_bool)
    kind = draw(st.sampled_from(list(apispec.RemoteKind))) if include_kind else None
    remote = None
    include_remote = draw(a_bool)
    if include_remote:
        # remote is only valid for FirecREST classes
        remote_kind = _to_apispec_kind(existing_kind) if existing_kind is not None else None
        if remote_kind is None or remote_kind == apispec.RemoteKind.firecrest:
            remote = draw(apispec_remote_class_configuration_firecrest_strat())

    return apispec.ResourceClassPatch(
        name=draw(st.one_of(st.none(), a_name)),
        default=draw(st.one_of(st.none(), a_bool)),
        cpu=draw(st.one_of(st.none(), a_cpu_float)),
        memory=draw(st.one_of(st.none(), st.integers(min_value=1, max_value=128))),
        gpu=draw(st.one_of(st.none(), st.integers(min_value=0, max_value=8))),
        max_storage=draw(st.one_of(st.none(), st.integers(min_value=1, max_value=1000))),
        default_storage=draw(st.one_of(st.none(), st.integers(min_value=1, max_value=1000))),
        tolerations=draw(st.one_of(st.none(), apispec_tolerations_strat())),
        node_affinities=draw(st.one_of(st.none(), st.lists(apispec_node_affinity_strat(), min_size=0, max_size=3))),
        quota_enforced=draw(st.one_of(st.none(), a_bool)),
        kind=kind,
        remote=remote,
    )


@st.composite
def apispec_resource_class_patch_with_id_strat(draw, *, existing_kind: models.RemoteConfigurationKind | None = None):
    """Generate a valid apispec.ResourceClassPatchWithId relative to an existing kind."""
    patch = draw(apispec_resource_class_patch_strat(existing_kind=existing_kind))
    return apispec.ResourceClassPatchWithId(
        id=draw(a_row_id),
        name=patch.name,
        default=patch.default,
        cpu=patch.cpu,
        memory=patch.memory,
        gpu=patch.gpu,
        max_storage=patch.max_storage,
        default_storage=patch.default_storage,
        tolerations=patch.tolerations,
        node_affinities=patch.node_affinities,
        quota_enforced=patch.quota_enforced,
        kind=patch.kind,
        remote=patch.remote,
    )


@st.composite
def apispec_resource_class_with_id_strat(draw, *, kind: apispec.RemoteKind | None = None):
    """Generate a valid apispec.ResourceClassWithId."""
    base = draw(apispec_resource_class_strat(kind=kind))
    return apispec.ResourceClassWithId(
        id=draw(a_row_id),
        name=base.name,
        default=base.default,
        cpu=base.cpu,
        memory=base.memory,
        gpu=base.gpu,
        max_storage=base.max_storage,
        default_storage=base.default_storage,
        tolerations=base.tolerations,
        node_affinities=base.node_affinities,
        quota_enforced=base.quota_enforced,
        kind=base.kind,
        remote=base.remote,
    )


@st.composite
def resource_class_model_strat(draw):
    """Generate a valid models.ResourceClass with an id."""
    default_storage = draw(st.integers(min_value=1, max_value=500))
    max_storage = draw(st.integers(min_value=default_storage, max_value=1000))
    return models.ResourceClass(
        id=draw(a_row_id),
        name=draw(a_name),
        cpu=draw(a_cpu_float),
        memory=draw(st.integers(min_value=1, max_value=128)),
        gpu=draw(st.integers(min_value=0, max_value=8)),
        max_storage=max_storage,
        kind=draw(st.sampled_from(list(models.RemoteConfigurationKind))),
        default=draw(a_bool),
        default_storage=default_storage,
        quota_enforced=draw(a_bool),
    )


@st.composite
def resource_class_patch_update_strat(
    draw,
    *,
    existing: models.ResourceClass,
    invalid_name: bool = False,
    invalid_default_storage: bool = False,
    invalid_kind: bool = False,
    invalid_default: bool = False,
):
    """Generate a models.ResourceClassPatch to apply to an existing class.

    The patch is guaranteed to be compatible unless one of the ``invalid_*`` flags is set.
    """
    name = draw(a_long_name) if invalid_name else draw(st.one_of(st.none(), a_name))

    if invalid_default_storage:
        default_storage = existing.max_storage + draw(st.integers(min_value=1, max_value=100))
    else:
        default_storage = draw(st.one_of(st.none(), st.integers(min_value=1, max_value=existing.max_storage)))

    if invalid_kind:
        kind_options = [k for k in models.RemoteConfigurationKind if k != existing.kind]
        kind = draw(st.sampled_from(kind_options))
    else:
        kind = draw(st.one_of(st.none(), st.just(existing.kind)))

    if invalid_default:
        default = draw(st.just(not existing.default))
    else:
        default = draw(st.one_of(st.none(), st.just(existing.default)))

    return models.ResourceClassPatch(
        name=name,
        default=default,
        cpu=draw(st.one_of(st.none(), a_cpu_float)),
        memory=draw(st.one_of(st.none(), st.integers(min_value=1, max_value=128))),
        gpu=draw(st.one_of(st.none(), st.integers(min_value=0, max_value=8))),
        max_storage=draw(st.one_of(st.none(), st.integers(min_value=max(default_storage or 1, 1), max_value=2000))),
        default_storage=default_storage,
        quota_enforced=draw(st.one_of(st.none(), a_bool)),
        kind=kind,
    )
