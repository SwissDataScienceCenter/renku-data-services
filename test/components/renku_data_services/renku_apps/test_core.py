"""Tests for app name generation."""

import re

import pytest
from ulid import ULID

from renku_data_services.renku_apps.core import APP_NAME_MAX_LENGTH, generate_app_name

_APP_NAME_PATTERN = re.compile(r"^[a-z]([-a-z0-9]*[a-z0-9])?$")


@pytest.mark.parametrize(
    "slug",
    [
        "p",
        "my-project",
        "renku-apps-with-data-connector-demo-rshiny",
        "a" * 200,
        "project.with.dots",
        "2024-analysis",
        "9",
        "MixedCaseSlug",
        "___",
    ],
)
def test_generated_name_satisfies_the_api_contract(slug: str) -> None:
    name = generate_app_name(slug, ULID())
    assert 5 <= len(name) <= APP_NAME_MAX_LENGTH
    assert _APP_NAME_PATTERN.match(name), name


def test_generated_name_differs_per_launcher() -> None:
    assert generate_app_name("my-project", ULID()) != generate_app_name("my-project", ULID())


@pytest.mark.parametrize(
    "slug",
    [
        "a" * 39 + "-tail",
        "a" * 40 + "-tail",
        "a" * 41 + "-tail",
        "a" * 42 + "-tail",
    ],
)
def test_truncation_does_not_leave_a_double_hyphen(slug: str) -> None:
    assert "--" not in generate_app_name(slug, ULID())
