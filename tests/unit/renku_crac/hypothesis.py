from typing import Dict

from hypothesis import strategies as st

import models


def make_cpu_float(data) -> Dict[str, int | float]:
    if "cpu" in data:
        data["cpu"] = float(data["cpu"])
    return data


SQL_BIGINT_MAX = 9_223_372_036_854_775_807
a_cpu = st.floats(min_value=0.0)
a_gpu = st.integers(min_value=0, max_value=SQL_BIGINT_MAX)
a_storage = st.integers(min_value=0, max_value=SQL_BIGINT_MAX)
a_memory = st.integers(min_value=0, max_value=SQL_BIGINT_MAX)
a_row_id = st.integers(min_value=1, max_value=SQL_BIGINT_MAX)
a_name = st.text(min_size=5)
a_uuid_string = st.uuids(version=4).map(lambda x: str(x))

rc_strat = st.builds(models.ResourceClass, name=a_name, cpu=a_cpu, gpu=a_gpu, storage=a_storage, memory=a_memory)
rc_set_strat = st.sets(rc_strat)
rc_set_strat_non_empty = st.sets(rc_strat, min_size=1)
quota_strat = st.builds(models.Quota, cpu=a_cpu, gpu=a_gpu, storage=a_storage, memory=a_memory)
rp_strat = st.builds(models.ResourcePool, name=a_name, quota=quota_strat, classes=rc_set_strat)
rp_list_strat = st.lists(rp_strat, min_size=1, max_size=5)
rp_strat_w_classes = st.builds(models.ResourcePool, name=a_name, quota=quota_strat, classes=rc_set_strat_non_empty)
user_strat = st.builds(models.User, keycloak_id=a_uuid_string)
user_list_strat = st.lists(user_strat, max_size=5, min_size=1)
rc_update_reqs_dict = st.dictionaries(
    keys=st.sampled_from(["cpu", "gpu", "memory", "storage"]),
    values=st.integers(min_value=0, max_value=SQL_BIGINT_MAX),
).map(make_cpu_float)
