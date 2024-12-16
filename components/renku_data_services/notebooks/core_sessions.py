"""A selection of core functions for AmaltheaSessions."""

from typing import Any

from sanic.response import JSONResponse, json

from renku_data_services.base_models.core import AnonymousAPIUser, AuthenticatedAPIUser
from renku_data_services.crc.db import ResourcePoolRepository
from renku_data_services.errors import errors
from renku_data_services.notebooks import apispec
from renku_data_services.notebooks.config import NotebooksConfig
from renku_data_services.notebooks.crs import State


async def patch_session(
    body: apispec.SessionPatchRequest,
    session_id: str,
    nb_config: NotebooksConfig,
    user: AnonymousAPIUser | AuthenticatedAPIUser,
    rp_repo: ResourcePoolRepository,
) -> JSONResponse:
    """Patch an Amalthea session."""
    session = await nb_config.k8s_v2_client.get_server(session_id, user.id)
    if session is None:
        raise errors.MissingResourceError(message=f"The sesison with ID {session_id} does not exist", quiet=True)
    # TODO: Some patching should only be done when the session is in some states to avoid inadvertent restarts
    patches: dict[str, Any] = {}
    if body.resource_class_id is not None:
        rcs = await rp_repo.get_classes(user, id=body.resource_class_id)
        if len(rcs) == 0:
            raise errors.MissingResourceError(
                message=f"The resource class you requested with ID {body.resource_class_id} does not exist",
                quiet=True,
            )
        rc = rcs[0]
        patches |= dict(
            spec=dict(
                session=dict(resources=dict(requests=dict(cpu=f"{round(rc.cpu * 1000)}m", memory=f"{rc.memory}Gi")))
            )
        )
        # TODO: Add a config to specifiy the gpu kind, there is also GpuKind enum in reosurce_pools
        patches["spec"]["session"]["resources"]["requests"]["nvidia.com/gpu"] = rc.gpu
        # NOTE: K8s fails if the gpus limit is not equal to the requests because it cannot be overcommited
        patches["spec"]["session"]["resources"]["limits"] = {"nvidia.com/gpu": rc.gpu}
    if (
        body.state is not None
        and body.state.value.lower() == State.Hibernated.value.lower()
        and body.state.value.lower() != session.status.state.value.lower()
    ):
        if "spec" not in patches:
            patches["spec"] = {}
        patches["spec"]["hibernated"] = True
    elif (
        body.state is not None
        and body.state.value.lower() == State.Running.value.lower()
        and session.status.state.value.lower() != body.state.value.lower()
    ):
        if "spec" not in patches:
            patches["spec"] = {}
        patches["spec"]["hibernated"] = False

    if len(patches) > 0:
        new_session = await nb_config.k8s_v2_client.patch_server(session_id, user.id, patches)
    else:
        new_session = session

    return json(new_session.as_apispec().model_dump(exclude_none=True, mode="json"))
