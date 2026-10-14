"""Tests for resource flavor precedence on resource classes."""

import pytest
from pydantic import ValidationError as PydanticValidationError
from ulid import ULID

from renku_data_services.base_models import RESET
from renku_data_services.crc import apispec, models, orm
from renku_data_services.crc.core import validate_resource_class, validate_resource_class_patch_or_put
from renku_data_services.errors import errors


def _flavor_orm(name: str = "small", **kwargs: float | int | str | None) -> orm.ResourceFlavorORM:
    values: dict = dict(name=name, cpu=2.0, memory=8, max_storage=200, default_storage=20, gpu=0)
    values.update(kwargs)
    flavor = orm.ResourceFlavorORM(**values)
    flavor.id = str(ULID())
    return flavor


def _class_orm(name: str = "own-name", **kwargs: float | int) -> orm.ResourceClassORM:
    values: dict = dict(name=name, cpu=1.0, memory=4, max_storage=100, default_storage=10, gpu=0)
    values.update(kwargs)
    return orm.ResourceClassORM(**values)


def test_dump_uses_own_values_when_unlinked() -> None:
    dumped = _class_orm().dump()
    assert dumped.name == "own-name"
    assert dumped.cpu == 1.0
    assert dumped.memory == 4
    assert dumped.resource_flavor_id is None


def test_dump_prefers_the_flavor_over_the_class() -> None:
    cls = _class_orm()
    flavor = _flavor_orm()
    cls.resource_flavor = flavor
    cls.resource_flavor_id = flavor.id

    dumped = cls.dump()

    assert dumped.name == "own-name", "the class keeps its own name, the flavor supplies only the resource values"
    assert dumped.cpu == 2.0
    assert dumped.memory == 8
    assert dumped.max_storage == 200
    assert dumped.default_storage == 20
    assert dumped.resource_flavor_id == flavor.id


def test_dump_matching_reads_the_resolved_values() -> None:
    """A stale snapshot must not decide whether a class matches a request."""
    cls = _class_orm(cpu=1.0, memory=4)
    flavor = _flavor_orm(cpu=16.0, memory=64)
    cls.resource_flavor = flavor
    cls.resource_flavor_id = flavor.id
    criteria = models.UnsavedResourceClass(name="wanted", cpu=8.0, memory=32, max_storage=50, gpu=0)

    assert cls.dump(matching_criteria=criteria).matching is True
    assert _class_orm(cpu=1.0, memory=4).dump(matching_criteria=criteria).matching is False


def test_pool_dump_sorts_by_the_resolved_size() -> None:
    """A pool lists its classes by their flavor size, not by the values saved on the class."""
    resolves_large = _class_orm("resolves-large", cpu=1.0, memory=2)
    resolves_small = _class_orm("resolves-small", cpu=32.0, memory=128)
    resolves_large.id, resolves_small.id = 1, 2
    huge = _flavor_orm("huge", cpu=32.0, memory=128)
    tiny = _flavor_orm("tiny", cpu=1.0, memory=2)
    resolves_large.resource_flavor, resolves_large.resource_flavor_id = huge, huge.id
    resolves_small.resource_flavor, resolves_small.resource_flavor_id = tiny, tiny.id

    pool = orm.ResourcePoolORM(name="pool", classes=[resolves_large, resolves_small])
    pool.id = 1

    assert [c.name for c in pool.dump(quota=None).classes] == ["resolves-small", "resolves-large"]


def test_validate_resource_class_fills_the_shape_from_the_flavor() -> None:
    flavor = models.ResourceFlavor(
        id=ULID(), name="small", cpu=2.0, memory=8, max_storage=200, default_storage=20, gpu=0
    )
    body = apispec.ResourceClass(name="my-class", default=False, resource_flavor_id=str(flavor.id))

    result = validate_resource_class(body=body, flavor=flavor)

    assert result.name == "my-class"
    assert result.cpu == 2.0
    assert result.max_storage == 200
    assert result.resource_flavor_id == flavor.id


def test_a_body_cannot_carry_both_a_link_and_a_shape() -> None:
    body = apispec.ResourceClass(name="my-class", default=False, cpu=4.0, resource_flavor_id=str(ULID()))
    with pytest.raises(errors.ValidationError):
        validate_resource_class(body=body)


def test_a_body_without_a_link_needs_the_whole_shape() -> None:
    body = apispec.ResourceClass(name="my-class", default=False, cpu=4.0)
    with pytest.raises(errors.ValidationError):
        validate_resource_class(body=body)


def test_a_put_body_without_a_link_needs_the_whole_shape() -> None:
    body = apispec.ResourceClass(name="my-class", default=False, cpu=4.0)
    with pytest.raises(errors.ValidationError):
        validate_resource_class_patch_or_put(body=body, method="PUT")


def test_a_body_always_needs_a_name() -> None:
    with pytest.raises(PydanticValidationError):
        apispec.ResourceClass.model_validate({"default": False, "resource_flavor_id": str(ULID())})


def test_a_new_class_cannot_send_an_empty_flavor_id() -> None:
    with pytest.raises(PydanticValidationError):
        apispec.ResourceClass.model_validate({"name": "my-class", "default": False, "resource_flavor_id": ""})


def test_flavor_id_in_a_patch_means_link() -> None:
    flavor_id = ULID()
    patch = validate_resource_class_patch_or_put(
        body=apispec.ResourceClassPatch(resource_flavor_id=str(flavor_id)), method="PATCH"
    )
    assert patch.resource_flavor_id == flavor_id


def test_an_empty_flavor_id_in_a_patch_means_unlink() -> None:
    patch = validate_resource_class_patch_or_put(body=apispec.ResourceClassPatch(resource_flavor_id=""), method="PATCH")
    assert patch.resource_flavor_id is RESET
