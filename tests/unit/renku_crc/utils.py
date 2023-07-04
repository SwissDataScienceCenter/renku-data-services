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
    quota = rp.quota
    if isinstance(quota, models.Quota):
        quota = remove_id_from_quota(quota)
    classes = [remove_id_from_rc(rc) for rc in rp.classes]
    return models.ResourcePool(
        name=rp.name, id=None, quota=quota, classes=classes, default=rp.default, public=rp.public
    )


def remove_id_from_user(user: models.User) -> models.User:
    kwargs = asdict(user)
    kwargs["id"] = None
    return models.User(**kwargs)


def create_rp(rp: models.ResourcePool, repo: ResourcePoolRepository, api_user: models.APIUser) -> models.ResourcePool:
    inserted_rp = asyncio.run(repo.insert_resource_pool(api_user, rp))
    assert inserted_rp is not None
    assert inserted_rp.id is not None
    assert inserted_rp.quota is not None
    assert all([rc.id is not None for rc in inserted_rp.classes])
    inserted_rp_no_ids = remove_id_from_rp(inserted_rp)
    assert rp == inserted_rp_no_ids, f"resource pools do not match {rp} != {inserted_rp_no_ids}"
    retrieved_rps = asyncio.run(repo.get_resource_pools(api_user, inserted_rp.id))
    assert len(retrieved_rps) == 1
    assert inserted_rp == retrieved_rps[0]
    return inserted_rp
