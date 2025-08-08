from dataclasses import dataclass

from renku_data_services.notebooks.core_sessions import _make_patch_spec_list


def test_make_patch_spec_list() -> None:
    @dataclass(eq=True)
    class MyResource:
        name: str
        contents: str

    existing = [
        MyResource(name="first", contents="first content"),
        MyResource(name="second", contents="second content"),
    ]
    updated = [
        MyResource(name="second", contents="second content patched"),
        MyResource(name="third", contents="new third content"),
    ]
    patch_list = _make_patch_spec_list(existing=existing, updated=updated)

    assert patch_list == [
        MyResource(name="first", contents="first content"),
        MyResource(name="second", contents="second content patched"),
        MyResource(name="third", contents="new third content"),
    ]
