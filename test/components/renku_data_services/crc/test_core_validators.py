"""Unit and property-based tests for CRC validators."""

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from renku_data_services.crc import apispec, models
from renku_data_services.crc.core import (
    validate_resource_class,
    validate_resource_class_patch_or_put,
    validate_resource_class_update,
    validate_resource_pool_put_or_patch,
    validate_resource_pool_update,
)
from renku_data_services.errors import errors
from test.components.renku_data_services.crc_models.hypothesis import (
    apispec_resource_class_invalid_strat,
    apispec_resource_class_patch_strat,
    apispec_resource_class_patch_with_id_strat,
    apispec_resource_class_strat,
    resource_class_model_strat,
    resource_class_patch_update_strat,
)


def _firecrest_body(cpu: int = 2, remote: dict | None = None) -> apispec.ResourceClass:
    return apispec.ResourceClass(
        name="firecrest-class",
        default=True,
        cpu=cpu,
        memory=8,
        gpu=0,
        max_storage=100,
        default_storage=1,
        remote=apispec.RemoteClassConfigurationFirecrest(**remote) if remote else None,
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
@given(body=apispec_resource_class_strat(pool_kind=st.just(None)))
def test_validate_local_class_valid(body: apispec.ResourceClass) -> None:
    """A local resource class validates successfully without a pool kind."""
    result = validate_resource_class(body)
    assert isinstance(result, models.UnsavedResourceClass)
    assert result.name == body.name
    assert result.cpu == body.cpu


@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(body=apispec_resource_class_strat(pool_kind=st.just(models.RemoteConfigurationKind.firecrest)))
def test_validate_firecrest_class_valid(body: apispec.ResourceClass) -> None:
    """A FirecREST class validates successfully when the pool kind matches."""
    result = validate_resource_class(body, pool_kind=models.RemoteConfigurationKind.firecrest)
    assert isinstance(result, models.UnsavedResourceClass)
    assert result.cpu == int(body.cpu)
    assert result.name == body.name


@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(body=apispec_resource_class_strat(pool_kind=st.just(models.RemoteConfigurationKind.runai)))
def test_validate_runai_class_valid(body: apispec.ResourceClass) -> None:
    """A Run:AI class validates successfully when the pool kind matches."""
    result = validate_resource_class(body, pool_kind=models.RemoteConfigurationKind.runai)
    assert isinstance(result, models.UnsavedResourceClass)


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
    pool_kind = models.RemoteConfigurationKind.firecrest if invalid_case == "firecrest_fractional_cpu" else None
    with pytest.raises(errors.ValidationError):
        validate_resource_class(body, pool_kind=pool_kind)


def test_validate_resource_class_patch_or_put_patch_firecrest_valid():
    """PATCH on a FirecREST class validates successfully."""
    body = apispec.ResourceClassPatch(
        name="firecrest-class",
        default=True,
        cpu=2,
        memory=8,
        gpu=0,
        max_storage=100,
        default_storage=1,
    )
    validate_resource_class_patch_or_put(body, method="PATCH", existing_kind=models.RemoteConfigurationKind.firecrest)


def test_validate_resource_class_patch_or_put_put_valid_no_existing_kind():
    """PUT on a resource class sets kind to None; the pool is the source of truth."""
    body = apispec.ResourceClass(
        name="firecrest-class",
        default=True,
        cpu=2,
        memory=8,
        gpu=0,
        max_storage=100,
        default_storage=1,
    )
    validate_resource_class_patch_or_put(body, method="PUT")


def test_validate_resource_class_put_accepts_remote_for_firecrest():
    """Standalone PUT on a FirecREST class accepts body.remote."""
    body = apispec.ResourceClass(
        name="fc-class",
        default=True,
        cpu=2,
        memory=8,
        gpu=0,
        max_storage=100,
        default_storage=1,
        remote=apispec.RemoteClassConfigurationFirecrest(system_name="eiger"),
    )
    result = validate_resource_class_patch_or_put(
        body, method="PUT", existing_kind=models.RemoteConfigurationKind.firecrest
    )
    assert result.remote is not None
    assert result.remote.system_name == "eiger"


def test_validate_resource_class_put_without_remote_succeeds():
    """Standalone PUT without remote in the body succeeds."""
    body = apispec.ResourceClass(
        name="fc-class",
        default=True,
        cpu=2,
        memory=8,
        gpu=0,
        max_storage=100,
        default_storage=1,
    )
    validate_resource_class_patch_or_put(body, method="PUT", existing_kind=models.RemoteConfigurationKind.firecrest)


# ---------------------------------------------------------------------------
# Property-based tests for PATCH/PUT helpers.
# ---------------------------------------------------------------------------


@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(body=apispec_resource_class_strat(pool_kind=st.just(None)))
def test_validate_resource_class_patch_or_put_put_valid(body: apispec.ResourceClass) -> None:
    """PUT with a fully populated body yields a valid ResourceClassPatch with kind None."""
    result = validate_resource_class_patch_or_put(body, method="PUT")
    assert isinstance(result, models.ResourceClassPatch)


@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(
    existing_kind=st.sampled_from([None, *list(models.RemoteConfigurationKind)]),
    body=apispec_resource_class_patch_strat(),
)
def test_validate_resource_class_patch_or_put_patch_valid(existing_kind, body) -> None:
    """PATCH derives the class kind from the existing class and validates successfully."""
    assume(body.remote is None or existing_kind == models.RemoteConfigurationKind.firecrest)
    result = validate_resource_class_patch_or_put(body, method="PATCH", existing_kind=existing_kind)
    assert isinstance(result, models.ResourceClassPatch)


@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(
    existing_kind=st.sampled_from([None, *list(models.RemoteConfigurationKind)]),
    body=apispec_resource_class_patch_with_id_strat(),
)
def test_validate_resource_class_patch_or_put_with_id_valid(existing_kind, body) -> None:
    """PATCH/PUT with an id preserves the id and produces ResourceClassPatchWithId."""
    assume(body.remote is None or existing_kind == models.RemoteConfigurationKind.firecrest)
    result = validate_resource_class_patch_or_put(body, method="PATCH", existing_kind=existing_kind)
    assert isinstance(result, models.ResourceClassPatchWithId)
    assert result.id == body.id


# ---------------------------------------------------------------------------
# Pool remote kind change validation.
# ---------------------------------------------------------------------------


def test_validate_resource_pool_put_or_patch_rejects_remote_on_non_firecrest_pool() -> None:
    """Converting a pool away from FirecREST is rejected if a class still has remote overrides."""
    body = apispec.ResourcePoolPatch(
        remote=apispec.RemoteConfigurationPatchReset(),
        classes=[
            apispec.ResourceClassPatchWithId(
                id=1,
                name="fc-class",
                remote=apispec.RemoteClassConfigurationFirecrest(system_name="eiger"),
            )
        ],
    )
    with pytest.raises(errors.ValidationError):
        validate_resource_pool_put_or_patch(
            method="PATCH", body=body, existing_pool_kind=models.RemoteConfigurationKind.firecrest
        )


def test_validate_resource_pool_put_or_patch_rejects_stored_remote_on_non_firecrest_pool() -> None:
    """Converting a pool away from FirecREST is rejected if a class has stored remote data."""
    existing_class = models.ResourceClass(
        id=1,
        name="fc-class",
        cpu=2.0,
        memory=8,
        max_storage=100,
        gpu=0,
        default=True,
        default_storage=1,
        remote=models.FirecrestClassRemote(system_name="eiger", partition="normal"),
    )
    body = apispec.ResourcePoolPatch(
        remote=apispec.RemoteConfigurationPatchReset(),
        classes=[apispec.ResourceClassPatchWithId(id=1, name="fc-class", cpu=2.0)],
    )
    with pytest.raises(errors.ValidationError):
        validate_resource_pool_put_or_patch(
            method="PATCH",
            body=body,
            existing_pool_kind=models.RemoteConfigurationKind.firecrest,
            existing_classes=[existing_class],
        )


def test_validate_resource_pool_put_or_patch_rejects_fractional_cpu_for_firecrest() -> None:
    """Converting a pool to FirecREST is rejected if a class has fractional CPU."""
    body = apispec.ResourcePoolPut(
        name="resource-pool",
        default=False,
        public=False,
        platform=apispec.RuntimePlatform.linux_amd64,
        remote=apispec.RemoteConfigurationFirecrest(
            kind="firecrest",
            api_url="https://firecrest.example.com",
            system_name="eiger",
        ),
        classes=[
            apispec.ResourceClassWithId(
                id=1,
                name="local-class",
                default=True,
                cpu=1.5,
                memory=4,
                gpu=0,
                max_storage=100,
                default_storage=1,
            )
        ],
    )
    with pytest.raises(errors.ValidationError):
        validate_resource_pool_put_or_patch(method="PUT", body=body, existing_pool_kind=None)


def test_validate_resource_pool_put_or_patch_converts_class_kind_on_pool_change() -> None:
    """When a pool's kind changes, provided classes are converted to the new kind."""
    body = apispec.ResourcePoolPatch(
        remote=apispec.RemoteConfigurationFirecrestPatch(
            kind="firecrest",
            api_url="https://firecrest.example.com",
            system_name="eiger",
        ),
        classes=[
            apispec.ResourceClassPatchWithId(
                id=1,
                name="local-class",
                cpu=2.0,
            )
        ],
    )
    result = validate_resource_pool_put_or_patch(method="PATCH", body=body, existing_pool_kind=None)
    assert result.classes is not None


def test_validate_resource_pool_update_allows_kind_change_via_pool_remote():
    """Pool update that changes the pool kind does not raise when class kind matches the new pool kind.

    This characterizes the path guarded by the (now-dead) class-kind-change check:
    rc.kind == new_pool_kind, so the guard never fires.
    """
    existing_pool = models.ResourcePool(
        id=1,
        name="local-pool",
        classes=[
            models.ResourceClass(
                id=1, name="c", cpu=2, memory=4, max_storage=10, gpu=0, default=True, default_storage=1
            )
        ],
        platform=models.RuntimePlatform.linux_amd64,
    )
    update = models.ResourcePoolPatch(
        remote=models.RemoteConfigurationFirecrestPatch(api_url="https://fc.example.com", system_name="eiger"),
        classes=[models.ResourceClassPatchWithId(id=1, cpu=2)],
    )
    validate_resource_pool_update(existing=existing_pool, update=update)


def test_validate_resource_pool_patch_allows_class_remote_on_local_to_firecrest_transition() -> None:
    """PATCH converting a local pool to FirecREST accepts a class remote override in the same request."""
    body = apispec.ResourcePoolPatch(
        remote=apispec.RemoteConfigurationFirecrestPatch(
            kind="firecrest",
            api_url="https://fc.example.com",
            system_name="eiger",
        ),
        classes=[
            apispec.ResourceClassPatchWithId(
                id=1,
                name="fc-class",
                cpu=2,
                remote=apispec.RemoteClassConfigurationFirecrest(system_name="eiger"),
            )
        ],
    )
    result = validate_resource_pool_put_or_patch(method="PATCH", body=body, existing_pool_kind=None)
    assert result.classes is not None
    assert result.classes[0].remote is not None
    assert result.classes[0].remote.system_name == "eiger"


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


def test_resource_class_models_have_no_kind_field():
    """Resource class models no longer carry a kind field — the pool is the source of truth."""
    rc = models.ResourceClass(id=1, name="c", cpu=2, memory=4, max_storage=10, gpu=0, default=True, default_storage=1)
    assert not hasattr(rc, "kind"), "ResourceClass should not have a kind field"
