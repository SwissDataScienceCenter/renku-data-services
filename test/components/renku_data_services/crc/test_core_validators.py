"""Unit and property-based tests for CRC validators."""

from typing import Any

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from renku_data_services.crc import apispec, models
from renku_data_services.crc.core import (
    validate_resource_class,
    validate_resource_class_patch_or_put,
    validate_resource_class_update,
)
from renku_data_services.errors import errors
from test.components.renku_data_services.crc_models.hypothesis import (
    apispec_resource_class_invalid_strat,
    apispec_resource_class_mismatch_kind_strat,
    apispec_resource_class_patch_strat,
    apispec_resource_class_patch_with_id_strat,
    apispec_resource_class_strat,
    resource_class_model_strat,
    resource_class_patch_update_strat,
)


def _firecrest_body(cpu: int = 2, remote: dict | None = None) -> apispec.ResourceClass:
    return apispec.ResourceClass(
        kind="firecrest",
        name="firecrest-class",
        default=True,
        cpu=cpu,
        memory=8,
        gpu=0,
        max_storage=100,
        default_storage=1,
        remote=apispec.RemoteClassConfigurationFirecrest(**remote) if remote else None,
    )


def _local_body() -> apispec.ResourceClass:
    return apispec.ResourceClass(
        kind="local",
        name="local-class",
        default=True,
        cpu=1.5,
        memory=4,
        gpu=0,
        max_storage=100,
        default_storage=1,
    )


def _runai_body() -> apispec.ResourceClass:
    return apispec.ResourceClass(
        kind="runai",
        name="runai-class",
        default=True,
        cpu=1.5,
        memory=4,
        gpu=0,
        max_storage=100,
        default_storage=1,
    )


# ---------------------------------------------------------------------------
# Example-based tests kept for readable documentation of specific edge cases.
# ---------------------------------------------------------------------------


def test_resource_class_orm_dump_deserializes_ignore_resource_class_values():
    from renku_data_services.crc.orm import ResourceClassORM

    orm = ResourceClassORM.from_unsaved_model(
        new_resource_class=models.UnsavedResourceClass(
            name="fc",
            cpu=2,
            memory=8,
            max_storage=100,
            gpu=0,
            kind=models.RemoteConfigurationKind.firecrest,
            remote=models.FirecrestClassRemote(
                system_name="eiger",
                ignore_resource_class_values=True,
            ),
        ),
        resource_pool_id=None,
    )
    dumped = orm.dump()
    assert dumped.remote is not None
    assert dumped.remote.ignore_resource_class_values is True


def test_validate_firecrest_class_preserves_ignore_resource_class_values():
    result = validate_resource_class(
        _firecrest_body(remote={"ignore_resource_class_values": True}),
        pool_kind=models.RemoteConfigurationKind.firecrest,
    )
    assert result.remote is not None
    assert result.remote.ignore_resource_class_values is True


def test_validate_firecrest_class_remote_override():
    result = validate_resource_class(
        _firecrest_body(remote={"system_name": "eiger", "partition": "normal"}),
        pool_kind=models.RemoteConfigurationKind.firecrest,
    )
    assert result.remote is not None
    assert result.remote.system_name == "eiger"
    assert result.remote.partition == "normal"


# ---------------------------------------------------------------------------
# Property-based tests for resource class creation.
# ---------------------------------------------------------------------------


@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(body=apispec_resource_class_strat(kind=st.just(apispec.RemoteKind.local)))
def test_validate_local_class_valid(body: apispec.ResourceClass) -> None:
    """A local resource class validates successfully without a pool kind."""
    result = validate_resource_class(body)
    assert isinstance(result, models.UnsavedResourceClass)
    assert result.kind == models.RemoteConfigurationKind.local
    assert result.name == body.name
    assert result.cpu == body.cpu


@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(body=apispec_resource_class_strat(kind=st.just(apispec.RemoteKind.firecrest)))
def test_validate_firecrest_class_valid(body: apispec.ResourceClass) -> None:
    """A FirecREST class validates successfully when the pool kind matches."""
    result = validate_resource_class(body, pool_kind=models.RemoteConfigurationKind.firecrest)
    assert isinstance(result, models.UnsavedResourceClass)
    assert result.kind == models.RemoteConfigurationKind.firecrest
    assert result.cpu == int(body.cpu)
    assert result.name == body.name


@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(body=apispec_resource_class_strat(kind=st.just(apispec.RemoteKind.runai)))
def test_validate_runai_class_valid(body: apispec.ResourceClass) -> None:
    """A Run:AI class validates successfully when the pool kind matches."""
    result = validate_resource_class(body, pool_kind=models.RemoteConfigurationKind.runai)
    assert isinstance(result, models.UnsavedResourceClass)
    assert result.kind == models.RemoteConfigurationKind.runai


@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(case=apispec_resource_class_mismatch_kind_strat())
def test_validate_resource_class_rejects_kind_mismatch(case: tuple[apispec.ResourceClass, Any]) -> None:
    """A resource class whose kind does not match the pool kind is rejected."""
    body, pool_kind = case
    with pytest.raises(errors.ValidationError):
        validate_resource_class(body, pool_kind=pool_kind)


@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(
    invalid_case=st.sampled_from(
        [
            "firecrest_fractional_cpu",
            "non_firecrest_with_remote",
            "name_too_long",
            "default_storage_larger_than_max",
        ]
    ),
    data=st.data(),
)
def test_validate_resource_class_rejects_invalid_case_split(invalid_case: str, data: st.DataObject) -> None:
    """Resource classes that violate explicit core rules are rejected."""
    body = data.draw(apispec_resource_class_invalid_strat(invalid_case=invalid_case))
    with pytest.raises(errors.ValidationError):
        validate_resource_class(body)


def test_validate_resource_class_patch_or_put_put_omitted_kind_uses_existing_kind():
    """PUT without kind uses the existing class kind, not local."""
    body = apispec.ResourceClassPatch(
        name="firecrest-class",
        default=True,
        cpu=2,
        memory=8,
        gpu=0,
        max_storage=100,
        default_storage=1,
    )
    result = validate_resource_class_patch_or_put(
        body, method="PUT", existing_kind=models.RemoteConfigurationKind.firecrest
    )
    assert result.kind == models.RemoteConfigurationKind.firecrest


def test_validate_resource_class_patch_or_put_rejects_kind_when_existing_unknown():
    """PATCH/PUT that provides a non-local kind when existing_kind is unknown is rejected."""
    body = apispec.ResourceClassPatch(kind="firecrest")
    with pytest.raises(errors.ValidationError):
        validate_resource_class_patch_or_put(body, method="PATCH", existing_kind=None)
    with pytest.raises(errors.ValidationError):
        validate_resource_class_patch_or_put(body, method="PUT", existing_kind=None)


# ---------------------------------------------------------------------------
# Property-based tests for PATCH/PUT helpers.
# ---------------------------------------------------------------------------


@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(body=apispec_resource_class_strat(kind=st.just(apispec.RemoteKind.local)))
def test_validate_resource_class_patch_or_put_put_valid(body: apispec.ResourceClass) -> None:
    """PUT with a fully populated body yields a valid ResourceClassPatch."""
    result = validate_resource_class_patch_or_put(body, method="PUT")
    assert isinstance(result, models.ResourceClassPatch)
    expected_kind = body.kind if body.kind is not None else models.RemoteConfigurationKind.local
    assert result.kind == expected_kind


@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(
    existing_kind=st.sampled_from(list(models.RemoteConfigurationKind)),
    body=apispec_resource_class_patch_strat(),
)
def test_validate_resource_class_patch_or_put_patch_valid(existing_kind: models.RemoteConfigurationKind, body) -> None:
    """PATCH with a kind matching the existing class validates successfully."""
    assume(body.kind is None or body.kind == existing_kind)
    assume(body.remote is None or existing_kind == models.RemoteConfigurationKind.firecrest)
    result = validate_resource_class_patch_or_put(body, method="PATCH", existing_kind=existing_kind)
    assert isinstance(result, models.ResourceClassPatch)
    assert result.kind == existing_kind


@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(
    existing_kind=st.sampled_from(list(models.RemoteConfigurationKind)),
    body=apispec_resource_class_patch_strat(),
)
def test_validate_resource_class_patch_or_put_rejects_kind_change(
    existing_kind: models.RemoteConfigurationKind, body
) -> None:
    """PATCH/PUT that changes the resource class kind is rejected."""
    assume(body.kind is not None and body.kind != existing_kind)
    with pytest.raises(errors.ValidationError):
        validate_resource_class_patch_or_put(body, method="PATCH", existing_kind=existing_kind)
    with pytest.raises(errors.ValidationError):
        validate_resource_class_patch_or_put(body, method="PUT", existing_kind=existing_kind)


@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(
    existing_kind=st.sampled_from(list(models.RemoteConfigurationKind)),
    body=apispec_resource_class_patch_with_id_strat(),
)
def test_validate_resource_class_patch_or_put_with_id_valid(
    existing_kind: models.RemoteConfigurationKind, body
) -> None:
    """PATCH/PUT with an id preserves the id and produces ResourceClassPatchWithId."""
    assume(body.kind is None or body.kind == existing_kind)
    assume(body.remote is None or existing_kind == models.RemoteConfigurationKind.firecrest)
    result = validate_resource_class_patch_or_put(body, method="PATCH", existing_kind=existing_kind)
    assert isinstance(result, models.ResourceClassPatchWithId)
    assert result.id == body.id


# ---------------------------------------------------------------------------
# Property-based tests for resource class updates.
# ---------------------------------------------------------------------------


@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(existing=resource_class_model_strat(), data=st.data())
def test_validate_resource_class_update_valid(existing: models.ResourceClass, data: st.DataObject) -> None:
    """A compatible update to a resource class succeeds."""
    update = data.draw(resource_class_patch_update_strat(existing=existing))
    validate_resource_class_update(existing, update)


@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(existing=resource_class_model_strat(), data=st.data())
def test_validate_resource_class_update_rejects_kind_change(
    existing: models.ResourceClass, data: st.DataObject
) -> None:
    """Changing the kind of an existing resource class is rejected."""
    update = data.draw(resource_class_patch_update_strat(existing=existing, invalid_kind=True))
    assume(update.kind is not None and update.kind != existing.kind)
    with pytest.raises(errors.ValidationError):
        validate_resource_class_update(existing, update)


@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(existing=resource_class_model_strat(), data=st.data())
def test_validate_resource_class_update_rejects_default_change(
    existing: models.ResourceClass, data: st.DataObject
) -> None:
    """Changing the default flag of an existing resource class is rejected."""
    update = data.draw(resource_class_patch_update_strat(existing=existing, invalid_default=True))
    assume(update.default is not None and update.default != existing.default)
    with pytest.raises(errors.ValidationError):
        validate_resource_class_update(existing, update)


@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(existing=resource_class_model_strat(), data=st.data())
def test_validate_resource_class_update_rejects_name_too_long(
    existing: models.ResourceClass, data: st.DataObject
) -> None:
    """An update that would set a name longer than 40 characters is rejected."""
    update = data.draw(resource_class_patch_update_strat(existing=existing, invalid_name=True))
    assume(update.name is not None and len(update.name) > 40)
    with pytest.raises(errors.ValidationError):
        validate_resource_class_update(existing, update)


@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(existing=resource_class_model_strat(), data=st.data())
def test_validate_resource_class_update_rejects_storage_inversion(
    existing: models.ResourceClass, data: st.DataObject
) -> None:
    """An update where default_storage exceeds max_storage is rejected."""
    update = data.draw(resource_class_patch_update_strat(existing=existing, invalid_default_storage=True))
    assume(update.default_storage is not None)
    max_storage = update.max_storage if update.max_storage is not None else existing.max_storage
    assume(update.default_storage > max_storage)
    with pytest.raises(errors.ValidationError):
        validate_resource_class_update(existing, update)
