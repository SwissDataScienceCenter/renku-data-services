from test.components.renku_data_services.user_preferences_models.hypothesis import (
    project_slug_strat,
    project_slugs_strat,
)
from test.utils import create_user_preferences
from typing import List

import pytest
from hypothesis import HealthCheck, given, settings, target

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.data_api.config import Config


@given(project_slug=project_slug_strat)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@pytest.mark.asyncio
async def test_user_preferences_insert_get(project_slug: str, app_config: Config, loggedin_user: base_models.APIUser):
    user_preferences_repo = app_config.user_preferences_repo
    try:
        await create_user_preferences(project_slug=project_slug, repo=user_preferences_repo, user=loggedin_user)
    finally:
        await user_preferences_repo.delete_user_preferences(user=loggedin_user)


@given(project_slugs=project_slugs_strat)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None, max_examples=25)
@pytest.mark.asyncio
async def test_user_preferences_add_pinned_project(
    project_slugs: List[str], app_config: Config, loggedin_user: base_models.APIUser
):
    target(len(project_slugs))
    user_preferences_repo = app_config.user_preferences_repo
    project_slugs = project_slugs[: app_config.user_preferences_config.max_pinned_projects]
    try:
        for project_slug in project_slugs:
            await user_preferences_repo.add_pinned_project(user=loggedin_user, project_slug=project_slug)

        res = await user_preferences_repo.get_user_preferences(user=loggedin_user)
        assert res.user_id == loggedin_user.id
        assert res.pinned_projects.project_slugs is not None
        assert len(res.pinned_projects.project_slugs) == len(project_slugs)
        assert sorted(res.pinned_projects.project_slugs) == sorted(project_slugs)
    finally:
        await user_preferences_repo.delete_user_preferences(user=loggedin_user)


@given(project_slugs=project_slugs_strat)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None, max_examples=25)
@pytest.mark.asyncio
async def test_user_preferences_add_pinned_project_existing(
    project_slugs: List[str], app_config: Config, loggedin_user: base_models.APIUser
):
    target(len(project_slugs))
    user_preferences_repo = app_config.user_preferences_repo
    project_slugs = project_slugs[: app_config.user_preferences_config.max_pinned_projects]
    try:
        for project_slug in project_slugs:
            await user_preferences_repo.add_pinned_project(user=loggedin_user, project_slug=project_slug)
        user_preferences_before = await user_preferences_repo.get_user_preferences(user=loggedin_user)

        await user_preferences_repo.add_pinned_project(user=loggedin_user, project_slug=project_slugs[0])

        user_preferences_after = await user_preferences_repo.get_user_preferences(user=loggedin_user)
        assert user_preferences_after.user_id == loggedin_user.id
        assert user_preferences_before.model_dump_json() == user_preferences_after.model_dump_json()
    finally:
        await user_preferences_repo.delete_user_preferences(user=loggedin_user)


@given(project_slugs=project_slugs_strat)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None, max_examples=25)
@pytest.mark.asyncio
async def test_user_preferences_delete_pinned_project(
    project_slugs: List[str], app_config: Config, loggedin_user: base_models.APIUser
):
    target(len(project_slugs))
    user_preferences_repo = app_config.user_preferences_repo
    project_slugs_valid = project_slugs[: app_config.user_preferences_config.max_pinned_projects]
    try:
        for project_slug in project_slugs_valid:
            await user_preferences_repo.add_pinned_project(user=loggedin_user, project_slug=project_slug)

        for project_slug in project_slugs:
            await user_preferences_repo.remove_pinned_project(user=loggedin_user, project_slug=project_slug)

        res = await user_preferences_repo.get_user_preferences(user=loggedin_user)
        assert res.user_id == loggedin_user.id
        assert res.pinned_projects.project_slugs is not None
        assert len(res.pinned_projects.project_slugs) == 0
    finally:
        await user_preferences_repo.delete_user_preferences(user=loggedin_user)


@given(project_slugs=project_slugs_strat)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None, max_examples=25)
@pytest.mark.asyncio
async def test_user_preferences_add_pinned_project_respects_maximum(
    project_slugs: List[str], app_config: Config, loggedin_user: base_models.APIUser
):
    target(len(project_slugs))
    user_preferences_repo = app_config.user_preferences_repo
    project_slugs_valid = project_slugs[: app_config.user_preferences_config.max_pinned_projects]
    project_slugs_invalid = project_slugs[app_config.user_preferences_config.max_pinned_projects :]
    try:
        for project_slug in project_slugs_valid:
            await user_preferences_repo.add_pinned_project(user=loggedin_user, project_slug=project_slug)

        for project_slug in project_slugs_invalid:
            with pytest.raises(
                errors.ValidationError, match=r"^ValidationError: Maximum number of pinned projects already allocated"
            ):
                await user_preferences_repo.add_pinned_project(user=loggedin_user, project_slug=project_slug)

        res = await user_preferences_repo.get_user_preferences(user=loggedin_user)
        assert res.user_id == loggedin_user.id
        assert res.pinned_projects.project_slugs is not None
        assert len(res.pinned_projects.project_slugs) == len(project_slugs_valid)
        assert sorted(res.pinned_projects.project_slugs) == sorted(project_slugs_valid)
    finally:
        await user_preferences_repo.delete_user_preferences(user=loggedin_user)
