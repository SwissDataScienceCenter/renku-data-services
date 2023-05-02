import asyncio
from dataclasses import asdict

import models
from db.adapter import ResourcePoolRepository


def remove_id_from_quota(quota: models.Quota) -> models.Quota:
    kwargs = asdict(quota)
    kwargs["id"] = None
    return models.Quota(**kwargs)


def remove_id_from_rc(rc: models.ResourceClass) -> models.ResourceClass:
    kwargs = asdict(rc)
    kwargs["id"] = None
    return models.ResourceClass(**kwargs)


def remove_id_from_rp(rp: models.ResourcePool) -> models.ResourcePool:
    quota = None
    if rp.quota is not None:
        quota = remove_id_from_quota(rp.quota)
    classes = set([remove_id_from_rc(rc) for rc in rp.classes])
    return models.ResourcePool(name=rp.name, id=None, quota=quota, classes=classes)


def remove_id_from_user(user: models.User) -> models.User:
    kwargs = asdict(user)
    kwargs["id"] = None
    return models.User(**kwargs)


def create_rp(rp: models.ResourcePool, repo: ResourcePoolRepository) -> models.ResourcePool:
    inserted_rp = asyncio.run(repo.insert_resource_pool(rp))
    assert inserted_rp is not None
    assert inserted_rp.id is not None
    assert inserted_rp.quota is not None
    assert inserted_rp.quota.id is not None
    assert all([rc.id is not None for rc in inserted_rp.classes])
    inserted_rp_no_ids = remove_id_from_rp(inserted_rp)
    assert rp == inserted_rp_no_ids
    retrieved_rps = asyncio.run(repo.get_resource_pools(inserted_rp.id))
    assert len(retrieved_rps) == 1
    assert inserted_rp == retrieved_rps[0]
    return inserted_rp
