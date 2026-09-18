"""Tests for resource flavour precedence on resource classes."""

import pytest
from pydantic import ValidationError as PydanticValidationError
from ulid import ULID

from renku_data_services.crc import apispec, models, orm
from renku_data_services.crc.core import validate_resource_class, validate_resource_class_patch_or_put


def _flavour_orm(name: str = "small", **kwargs: float | int | str | None) -> orm.ResourceFlavourORM:
    values: dict = dict(name=name, cpu=2.0, memory=8, max_storage=200, default_storage=20, gpu=0)
    values.update(kwargs)
    flavour = orm.ResourceFlavourORM(**values)
    flavour.id = str(ULID())
    return flavour


def _class_orm(name: str = "own-name", **kwargs: float | int) -> orm.ResourceClassORM:
    values: dict = dict(name=name, cpu=1.0, memory=4, max_storage=100, default_storage=10, gpu=0)
    values.update(kwargs)
    return orm.ResourceClassORM(**values)


def test_dump_uses_own_values_when_unlinked() -> None:
    dumped = _class_orm().dump()
    assert dumped.name == "own-name"
    assert dumped.cpu == 1.0
    assert dumped.memory == 4
    assert dumped.resource_flavour_id is None


def test_dump_prefers_the_flavour_over_the_class() -> None:
    cls = _class_orm()
    flavour = _flavour_orm()
    cls.resource_flavour = flavour
    cls.resource_flavour_id = flavour.id

    dumped = cls.dump()

    assert dumped.name == "own-name", "the class keeps its own name, the flavour supplies only the resource values"
    assert dumped.cpu == 2.0
    assert dumped.memory == 8
    assert dumped.max_storage == 200
    assert dumped.default_storage == 20
    assert dumped.resource_flavour_id == flavour.id


def test_dump_matching_reads_the_resolved_values() -> None:
    """A stale snapshot must not decide whether a class matches a request."""
    cls = _class_orm(cpu=1.0, memory=4)
    flavour = _flavour_orm(cpu=16.0, memory=64)
    cls.resource_flavour = flavour
    cls.resource_flavour_id = flavour.id
    criteria = models.UnsavedResourceClass(name="wanted", cpu=8.0, memory=32, max_storage=50, gpu=0)

    assert cls.dump(matching_criteria=criteria).matching is True
    assert _class_orm(cpu=1.0, memory=4).dump(matching_criteria=criteria).matching is False


def test_pool_dump_sorts_by_the_resolved_size() -> None:
    """The class rows are stale, so the SQL order is wrong and the Python sort has to fix it."""
    # Row values and ids are both in the opposite order to the resolved sizes, so an unsorted
    # dump, or one sorted on the class's own columns, returns these the other way round.
    resolves_large = _class_orm("resolves-large", cpu=1.0, memory=2)
    resolves_small = _class_orm("resolves-small", cpu=32.0, memory=128)
    resolves_large.id, resolves_small.id = 1, 2
    huge = _flavour_orm("huge", cpu=32.0, memory=128)
    tiny = _flavour_orm("tiny", cpu=1.0, memory=2)
    resolves_large.resource_flavour, resolves_large.resource_flavour_id = huge, huge.id
    resolves_small.resource_flavour, resolves_small.resource_flavour_id = tiny, tiny.id

    pool = orm.ResourcePoolORM(name="pool", classes=[resolves_large, resolves_small])
    pool.id = 1

    assert [c.name for c in pool.dump(quota=None).classes] == ["resolves-small", "resolves-large"]


def test_validate_resource_class_fills_the_shape_from_the_flavour() -> None:
    flavour = models.ResourceFlavour(
        id=ULID(), name="small", cpu=2.0, memory=8, max_storage=200, default_storage=20, gpu=0
    )
    body = apispec.ResourceClassFromFlavour(name="my-class", default=False, resource_flavour_id=str(flavour.id))

    result = validate_resource_class(body=body, flavour=flavour)

    assert result.name == "my-class"
    assert result.cpu == 2.0
    assert result.max_storage == 200
    assert result.resource_flavour_id == flavour.id


def test_a_body_cannot_carry_both_a_link_and_a_shape() -> None:
    with pytest.raises(PydanticValidationError):
        apispec.ResourceClassCreate.model_validate(
            {"name": "my-class", "default": False, "cpu": 4.0, "resource_flavour_id": str(ULID())}
        )


def test_a_body_without_a_link_needs_the_whole_shape() -> None:
    with pytest.raises(PydanticValidationError):
        apispec.ResourceClassCreate.model_validate({"name": "my-class", "default": False, "cpu": 4.0})


def test_a_body_always_needs_a_name() -> None:
    with pytest.raises(PydanticValidationError):
        apispec.ResourceClassCreate.model_validate({"default": False, "resource_flavour_id": str(ULID())})


def test_flavour_id_in_a_patch_means_link() -> None:
    flavour_id = ULID()
    patch = validate_resource_class_patch_or_put(
        body=apispec.ResourceClassPatch(resource_flavour_id=str(flavour_id)), method="PATCH"
    )
    assert patch.resource_flavour_id == flavour_id
