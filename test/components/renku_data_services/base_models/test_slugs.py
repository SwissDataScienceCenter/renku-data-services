import pytest

from renku_data_services.base_models.core import Slug
from renku_data_services.errors import errors


@pytest.mark.parametrize(
    "input, expected",
    [
        ("__test", "test"),
        ("test__", "test"),
        ("some-value.git", "some-value"),
        ("some-value.atom", "some-value"),
        ("consecutive___symbols-_-test", "consecutive_symbols-test"),
        ("UPPERCASE_TEST_&&&&", "uppercase_test"),
        ("uppERCAsE_TESt_&&&&", "uppercase_test"),
        ("123_test@test.com", "123_test-test.com"),
        ("😀_some_value", "some_value"),
        ("123連句@test.com", "123-test.com"),
        ("123-連句@_test.com", "123-test.com"),
        ("連句1", "1"),
    ],
)
def test_slug_generation_from_invalid_name(input: str, expected: str):
    with pytest.raises(errors.ValidationError):
        Slug(input)
    assert Slug.from_name(input).value == expected


@pytest.mark.parametrize(
    "input, expected",
    [
        ("t", "t"),
        ("A", "a"),
        ("SoMe_Value", "some_value"),
        ("w-e_i.r.d", "w-e_i.r.d"),
        ("some-value.com", "some-value.com"),
    ],
)
def test_valid_slug(input: str, expected: str):
    assert Slug(input).value == expected
    assert Slug.from_name(input).value == expected


@pytest.mark.parametrize(
    "input",
    [
        "😀😃😄😁",
        "_)(_++)_(",
        "___-----...",
        "連句",
        "",
    ],
)
def test_slug_generation_unrecoverable(input: str):
    with pytest.raises(errors.ValidationError):
        Slug(input)
        Slug.from_name(input)
