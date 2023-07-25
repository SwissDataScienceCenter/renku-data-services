from typing import Dict

import renku_data_services.base_models as base_models
import renku_data_services.resource_pool_models as models
from hypothesis import strategies as st


def make_cpu_float(data) -> Dict[str, int | float]:
    if "cpu" in data:
        data["cpu"] = float(data["cpu"])
    return data


SQL_BIGINT_MAX = 9_223_372_036_854_775_807
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
a_name = st.text(min_size=5)
a_uuid_string = st.uuids(version=4).map(lambda x: str(x))
a_bool = st.booleans()


@st.composite
def rc_non_default_strat(draw):
    return models.ResourceClass(
        name=draw(a_name),
        cpu=draw(a_rc_cpu),
        gpu=draw(a_rc_gpu),
        max_storage=draw(a_rc_storage),
        memory=draw(a_rc_memory),
        default=False,
    )


@st.composite
def rc_default_strat(draw):
    return models.ResourceClass(
        name=draw(a_name),
        cpu=draw(a_rc_cpu),
        gpu=draw(a_rc_gpu),
        max_storage=draw(a_rc_storage),
        memory=draw(a_rc_memory),
        default=True,
    )


quota_strat = st.builds(models.Quota, cpu=a_quota_cpu, gpu=a_quota_gpu, memory=a_quota_memory)


@st.composite
def rp_strat(draw):
    quota = draw(a_uuid_string)
    classes = draw(st.lists(rc_non_default_strat(), min_size=1, max_size=5))
    classes.append(draw(rc_default_strat()))
    default = False
    public = draw(a_bool)
    name = draw(a_name)
    return models.ResourcePool(name=name, classes=classes, quota=quota, default=default, public=public)


public_rp_strat = rp_strat().filter(lambda x: x.public)
private_rp_strat = rp_strat().filter(lambda x: not x.public)
rp_list_strat = st.lists(rp_strat(), min_size=1, max_size=5)
user_strat = st.builds(base_models.User, keycloak_id=a_uuid_string)
user_list_strat = st.lists(user_strat, max_size=5, min_size=1)


rc_update_reqs_dict = st.dictionaries(
    keys=st.sampled_from(["cpu", "gpu", "memory", "max_storage"]),
    values=st.integers(min_value=1, max_value=5),
    min_size=1,
).map(make_cpu_float)

quota_update_reqs_dict = st.dictionaries(
    keys=st.sampled_from(["cpu", "gpu", "memory", "storage"]),
    values=st.integers(min_value=1, max_value=5),
    min_size=1,
).map(make_cpu_float)
