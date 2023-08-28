from dataclasses import asdict
from typing import Any

import renku_data_services.base_models as base_models
import renku_data_services.resource_pool_models as rp_models
import renku_data_services.storage_models as storage_models
from renku_data_services.resource_pool_adapters import ResourcePoolRepository
from renku_data_services.storage_adapters import StorageRepository


def remove_id_from_quota(quota: rp_models.Quota) -> rp_models.Quota:
    kwargs = asdict(quota)
    kwargs["id"] = None
    return rp_models.Quota(**kwargs)


def remove_id_from_rc(rc: rp_models.ResourceClass) -> rp_models.ResourceClass:
    kwargs = asdict(rc)
    kwargs["id"] = None
    return rp_models.ResourceClass(**kwargs)


def remove_id_from_rp(rp: rp_models.ResourcePool) -> rp_models.ResourcePool:
    quota = rp.quota
    if isinstance(quota, rp_models.Quota):
        quota = remove_id_from_quota(quota)
    classes = [remove_id_from_rc(rc) for rc in rp.classes]
    return rp_models.ResourcePool(
        name=rp.name, id=None, quota=quota, classes=classes, default=rp.default, public=rp.public
    )


def remove_id_from_user(user: base_models.User) -> base_models.User:
    kwargs = asdict(user)
    kwargs["id"] = None
    return base_models.User(**kwargs)


async def create_rp(
    rp: rp_models.ResourcePool, repo: ResourcePoolRepository, api_user: base_models.APIUser
) -> rp_models.ResourcePool:
    inserted_rp = await repo.insert_resource_pool(api_user, rp)
    assert inserted_rp is not None
    assert inserted_rp.id is not None
    assert inserted_rp.quota is not None
    assert all([rc.id is not None for rc in inserted_rp.classes])
    inserted_rp_no_ids = remove_id_from_rp(inserted_rp)
    assert rp == inserted_rp_no_ids, f"resource pools do not match {rp} != {inserted_rp_no_ids}"
    retrieved_rps = await repo.get_resource_pools(api_user, inserted_rp.id)
    assert len(retrieved_rps) == 1
    assert inserted_rp == retrieved_rps[0]
    return inserted_rp


async def create_storage(storage_dict: dict[str, Any], repo: StorageRepository, user: base_models.GitlabAPIUser):
    storage_dict["configuration"] = storage_models.RCloneConfig.model_validate(storage_dict["configuration"])
    storage = storage_models.CloudStorage.model_validate(storage_dict)

    inserted_storage = await repo.insert_storage(storage, user=user)
    assert inserted_storage is not None
    assert inserted_storage.storage_id is not None
    retrieved_storage = await repo.get_storage_by_id(inserted_storage.storage_id, user=user)
    assert retrieved_storage is not None

    assert inserted_storage.model_dump() == retrieved_storage.model_dump()
    return inserted_storage
