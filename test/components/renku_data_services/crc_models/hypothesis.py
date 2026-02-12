from typing import Union

from hypothesis import assume
from hypothesis import strategies as st

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.crc import models
from renku_data_services.crc.constants import DEFAULT_RUNTIME_PLATFORM


def make_cpu_float(data: dict[str, Union[float, int]]) -> dict[str, int | float]:
    if "cpu" in data:
        data["cpu"] = float(data["cpu"])
    return data


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
