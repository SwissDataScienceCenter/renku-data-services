from hypothesis import strategies as st
from hypothesis.provisional import urls

a_project_id = st.integers(min_value=1, max_value=99999999).map(lambda x: str(x))
a_path = st.lists(
    st.text(alphabet=st.characters(blacklist_categories=("C", "Zl", "Zp"), blacklist_characters=["/"]), min_size=1),
    min_size=1,
    max_size=64,
).map(lambda x: "/".join(x))


@st.composite
def s3_configuration(draw):
    providers = draw(
        st.dictionaries(
            keys=st.just("provider"), values=st.sampled_from(["Other", "AWS", "GCS"]), min_size=0, max_size=1
        )
    )
    region = draw(st.dictionaries(keys=st.just("region"), values=st.text(), min_size=0, max_size=1))
    endpoint = draw(st.dictionaries(keys=st.just("endpoint"), values=urls(), min_size=0))
    return {"type": "s3", **providers, **region, **endpoint}


@st.composite
def azure_configuration(draw):
    account = draw(st.dictionaries(keys=st.just("account"), values=st.text(min_size=5)))
    endpoint = draw(st.dictionaries(keys=st.just("endpoint"), values=urls(), min_size=0))
    return {"type": "azureblob", **account, **endpoint}


@st.composite
def storage_strat(draw):
    project_id = draw(a_project_id)
    source_path = draw(a_path)
    target_path = draw(a_path)
    configuration = draw(st.one_of(s3_configuration(), azure_configuration()))

    return {
        "project_id": project_id,
        "storage_type": configuration["type"],
        "source_path": source_path,
        "target_path": target_path,
        "configuration": configuration,
    }
