"""Business logic for sessions."""

from pathlib import PurePosixPath

from ulid import ULID

from renku_data_services import errors
from renku_data_services.base_models.core import RESET, ResetType
from renku_data_services.session import apispec, models


def validate_unsaved_environment(
    environment: apispec.EnvironmentPost, environment_kind: models.EnvironmentKind
) -> models.UnsavedEnvironment:
    """Validate an unsaved session environment."""
    return models.UnsavedEnvironment(
        name=environment.name,
        description=environment.description,
        container_image=environment.container_image,
        default_url=environment.default_url,
        port=environment.port,
        working_directory=PurePosixPath(environment.working_directory),
        mount_directory=PurePosixPath(environment.mount_directory),
        uid=environment.uid,
        gid=environment.gid,
        environment_kind=environment_kind,
        args=environment.args,
        command=environment.command,
    )


def validate_environment_patch(patch: apispec.EnvironmentPatch) -> models.EnvironmentPatch:
    """Validate the update to a session environment."""
    data_dict = patch.model_dump(exclude_unset=True, mode="json")
    return models.EnvironmentPatch(
        name=patch.name,
        description=patch.description,
        container_image=patch.container_image,
        default_url=patch.default_url,
        port=patch.port,
        working_directory=PurePosixPath(patch.working_directory) if patch.working_directory else None,
        mount_directory=PurePosixPath(patch.mount_directory) if patch.mount_directory else None,
        uid=patch.uid,
        gid=patch.gid,
        args=RESET if "args" in data_dict and data_dict["args"] is None else patch.args,
        command=RESET if "command" in data_dict and data_dict["command"] is None else patch.command,
    )


def validate_unsaved_session_launcher(launcher: apispec.SessionLauncherPost) -> models.UnsavedSessionLauncher:
    """Validate an unsaved session launcher."""
    return models.UnsavedSessionLauncher(
        project_id=ULID.from_str(launcher.project_id),
        name=launcher.name,
        description=launcher.description,
        resource_class_id=launcher.resource_class_id,
        # NOTE: When you create an environment with a launcher the environment can only be custom
        environment=validate_unsaved_environment(launcher.environment, models.EnvironmentKind.CUSTOM)
        if isinstance(launcher.environment, apispec.EnvironmentPostInLauncher)
        else launcher.environment.id,
    )


def validate_session_launcher_patch(
    patch: apispec.SessionLauncherPatch, current_launcher: models.SessionLauncher
) -> models.SessionLauncherPatch:
    """Validate the update to a session launcher."""
    data_dict = patch.model_dump(exclude_unset=True, mode="json")
    environment: str | models.EnvironmentPatch | models.UnsavedEnvironment | None = None
    if (
        isinstance(patch.environment, apispec.EnvironmentPatchInLauncher)
        and current_launcher is not None
        and current_launcher.environment.environment_kind == models.EnvironmentKind.GLOBAL
        and patch.environment.environment_kind == apispec.EnvironmentKind.CUSTOM
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
    elif isinstance(patch.environment, apispec.EnvironmentPatchInLauncher):
        environment = validate_environment_patch(patch.environment)
    elif isinstance(patch.environment, apispec.EnvironmentIdOnlyPatch):
        environment = patch.environment.id
    resource_class_id: int | None | ResetType = None
    if "resource_class_id" in data_dict and data_dict["resource_class_id"] is None:
        # NOTE: This means that the resource class set in the DB should be removed so that the
        # default resource class currently set in the CRC will be used.
        resource_class_id = RESET
    else:
        resource_class_id = patch.resource_class_id
    return models.SessionLauncherPatch(
        name=patch.name,
        description=patch.description,
        environment=environment,
        resource_class_id=resource_class_id,
    )


def validate_unsaved_session_launcher_secret_slot(
    body: apispec.SessionSecretSlotPost,
) -> models.UnsavedSessionLauncherSecretSlot:
    """Validate an unsaved secret slot."""
    _validate_session_launcher_secret_slot_filename(body.filename)
    return models.UnsavedSessionLauncherSecretSlot(
        session_launcher_id=ULID.from_str(body.session_launcher_id),
        name=body.name,
        description=body.description,
        filename=body.filename,
    )


def validate_session_launcher_secret_slot_patch(
    body: apispec.SessionSecretSlotPatch,
) -> models.SessionLauncherSecretSlotPatch:
    """Validate the update to a secret slot."""
    if body.filename is not None:
        _validate_session_launcher_secret_slot_filename(body.filename)
    return models.SessionLauncherSecretSlotPatch(
        name=body.name,
        description=body.description,
        filename=body.filename,
    )


def validate_session_launcher_secrets_patch(
    body: apispec.SessionSecretPatchList,
) -> list[models.SessionSecretPatchExistingSecret | models.SessionSecretPatchSecretValue]:
    """Validate the update to a session launcher's secrets."""
    result: list[models.SessionSecretPatchExistingSecret | models.SessionSecretPatchSecretValue] = []
    seen_slot_ids: set[str] = set()
    for item in body.root:
        if item.secret_slot_id in seen_slot_ids:
            raise errors.ValidationError(
                message=f"Found duplicate secret_slot_id '{item.secret_slot_id}' in the list of secrets."
            )
        seen_slot_ids.add(item.secret_slot_id)

        if isinstance(item, apispec.SessionSecretPatch2):
            result.append(
                models.SessionSecretPatchExistingSecret(
                    secret_slot_id=ULID.from_str(item.secret_slot_id),
                    secret_id=ULID.from_str(item.secret_id),
                )
            )
        else:
            result.append(
                models.SessionSecretPatchSecretValue(
                    secret_slot_id=ULID.from_str(item.secret_slot_id),
                    value=item.value,
                )
            )
    return result


def _validate_session_launcher_secret_slot_filename(filename: str) -> None:
    """Validate the filename field of a secret slot."""
    filename_candidate = PurePosixPath(filename)
    if filename_candidate.name != filename:
        raise errors.ValidationError(message=f"Filename {filename} is not valid.")
