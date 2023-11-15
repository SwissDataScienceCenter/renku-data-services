from hypothesis import strategies as st

a_user_id = st.uuids(version=4).map(lambda x: str(x))
a_project_namespace_or_name = st.text(
    alphabet=st.characters(categories=("Lu", "Ll", "Nd"), include_characters=("-", "_")), min_size=3
)
a_project_slug = st.lists(
    a_project_namespace_or_name,
    min_size=2,
    max_size=5,
).map(lambda x: "/".join(x))
a_pinned_projects = st.dictionaries(
    keys=st.just("project_slugs"), values=st.lists(a_project_slug, min_size=0, max_size=10, unique=True)
)

project_slug_strat = a_project_slug
project_slugs_strat = st.lists(a_project_slug, min_size=1, max_size=10, unique=True)
