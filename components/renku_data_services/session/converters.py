"""Code used to convert from/to apispec and models."""

from pathlib import PurePosixPath

from renku_data_services.base_models.core import RESET, ResetType
from renku_data_services.session import apispec, models


def environment_update_from_patch(data: apispec.EnvironmentPatch) -> models.EnvironmentUpdate:
    """Create an update object from an apispec or any other pydantic model."""
    data_dict = data.model_dump(exclude_unset=True, mode="json")
    working_directory: PurePosixPath | None = None
    if data.working_directory is not None:
        working_directory = PurePosixPath(data.working_directory)
    mount_directory: PurePosixPath | None = None
    if data.mount_directory is not None:
        mount_directory = PurePosixPath(data.mount_directory)
    # NOTE: If the args or command are present in the data_dict and they are None they were passed in by the user.
    # The None specifically passed by the user indicates that the value should be removed from the DB.
    args = RESET if "args" in data_dict and data_dict["args"] is None else data.args
    command = RESET if "command" in data_dict and data_dict["command"] is None else data.command
    return models.EnvironmentUpdate(
        name=data.name,
        description=data.description,
        container_image=data.container_image,
        default_url=data.default_url,
        port=data.port,
        working_directory=working_directory,
        mount_directory=mount_directory,
        uid=data.uid,
        gid=data.gid,
        args=args,
        command=command,
    )


def launcher_update_from_patch(
    data: apispec.SessionLauncherPatch,
    current_launcher: models.SessionLauncher | None = None,
) -> models.SessionLauncherUpdate:
    """Create an update object from an apispec or any other pydantic model."""
    data_dict = data.model_dump(exclude_unset=True, mode="json")
    environment: str | models.EnvironmentUpdate | models.UnsavedEnvironment | None = None
    if (
        isinstance(data.environment, apispec.EnvironmentPatchInLauncher)
        and current_launcher is not None
        and current_launcher.environment.environment_kind == models.EnvironmentKind.GLOBAL
        and data.environment.environment_kind == apispec.EnvironmentKind.CUSTOM
    ):
        # This means that the global environment is being swapped for a custom one,
        # so we have to create a brand new environment, but we have to validate here.
        validated_env = apispec.EnvironmentPostInLauncher.model_validate(data_dict["environment"])
        environment = models.UnsavedEnvironment(
            name=validated_env.name,
            description=validated_env.description,
            container_image=validated_env.container_image,
            default_url=validated_env.default_url,
            port=validated_env.port,
            working_directory=PurePosixPath(validated_env.working_directory),
            mount_directory=PurePosixPath(validated_env.mount_directory),
            uid=validated_env.uid,
            gid=validated_env.gid,
            environment_kind=models.EnvironmentKind(validated_env.environment_kind.value),
            args=validated_env.args,
            command=validated_env.command,
        )
    elif isinstance(data.environment, apispec.EnvironmentPatchInLauncher):
        environment = environment_update_from_patch(data.environment)
    elif isinstance(data.environment, apispec.EnvironmentIdOnlyPatch):
        environment = data.environment.id
    resource_class_id: int | None | ResetType = None
    if "resource_class_id" in data_dict and data_dict["resource_class_id"] is None:
        # NOTE: This means that the resource class set in the DB should be removed so that the
        # default resource class currently set in the CRC will be used.
        resource_class_id = RESET
    else:
        resource_class_id = data_dict.get("resource_class_id")
    return models.SessionLauncherUpdate(
        name=data_dict.get("name"),
        description=data_dict.get("description"),
        environment=environment,
        resource_class_id=resource_class_id,
    )
