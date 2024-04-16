from hypothesis import strategies as st
from hypothesis.provisional import urls

a_project_id = st.integers(min_value=1, max_value=99999999).map(lambda x: str(x))
a_path = st.lists(
    st.text(alphabet=st.characters(blacklist_categories=("C", "Zl", "Zp"), blacklist_characters=["/"]), min_size=1),
    min_size=1,
    max_size=64,
).map(lambda x: "/".join(x))
a_storage_name = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters=("-", "_")), min_size=3
)


@st.composite
def s3_configuration(draw):
    providers = draw(
        st.dictionaries(
            keys=st.just("provider"), values=st.sampled_from(["Other", "AWS", "GCS"]), min_size=0, max_size=1
        )
    )
    region = draw(
        st.dictionaries(
            keys=st.just("region"),
            values=st.text(alphabet=st.characters(codec="utf-8", exclude_characters=["\x00"])),
            min_size=0,
            max_size=1,
        )
    )
    endpoint = draw(st.dictionaries(keys=st.just("endpoint"), values=urls(), min_size=0))
    return {"type": "s3", **providers, **region, **endpoint}


@st.composite
def azure_configuration(draw):
    account = draw(
        st.dictionaries(
            keys=st.just("account"),
            values=st.text(min_size=5, alphabet=st.characters(codec="utf-8", exclude_characters=["\x00"])),
        )
    )
    endpoint = draw(st.dictionaries(keys=st.just("endpoint"), values=urls(), min_size=0))
    return {"type": "azureblob", **account, **endpoint}


@st.composite
def storage_strat(draw):
    project_id = draw(a_project_id)
    storage_name = draw(a_storage_name)
    source_path = draw(a_path)
    target_path = draw(a_path)
    configuration = draw(st.one_of(s3_configuration(), azure_configuration()))

    return {
        "project_id": project_id,
        "name": storage_name,
        "storage_type": configuration["type"],
        "source_path": source_path,
        "target_path": target_path,
        "configuration": configuration,
    }
