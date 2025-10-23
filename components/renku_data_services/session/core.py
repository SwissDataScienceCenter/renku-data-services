"""Business logic for sessions."""

from pathlib import PurePosixPath
from typing import Union, cast

from ulid import ULID

from renku_data_services import errors
from renku_data_services.base_models.core import RESET, ResetType
from renku_data_services.session import apispec, models
from renku_data_services.session.config import BuildsConfig


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
        working_directory=PurePosixPath(environment.working_directory) if environment.working_directory else None,
        mount_directory=PurePosixPath(environment.mount_directory) if environment.mount_directory else None,
        uid=environment.uid,
        gid=environment.gid,
        environment_kind=environment_kind,
        args=environment.args,
        command=environment.command,
        is_archived=environment.is_archived,
        environment_image_source=models.EnvironmentImageSource.image,
        strip_path_prefix=environment.strip_path_prefix or False,
    )


def validate_unsaved_build_parameters(
    environment: apispec.BuildParameters | apispec.BuildParametersPatch,
    builds_config: "BuildsConfig",
) -> models.UnsavedBuildParameters:
    """Validate an unsaved build parameters object."""
    if not builds_config.enabled:
        raise errors.ValidationError(
            message="Image builds are not enabled, the field 'environment_image_source' cannot be set to 'build'."
        )
    if environment.builder_variant is None:
        raise errors.ValidationError(message="The field 'builder_variant' is required")
    if environment.frontend_variant is None:
        raise errors.ValidationError(message="The field 'frontend_variant' is required")
    if environment.repository is None:
        raise errors.ValidationError(message="The field 'repository' is required")
    if environment.builder_variant not in models.BuilderVariant:
        raise errors.ValidationError(
            message=(
                f"Invalid value for the field 'builder_variant': {environment.builder_variant}: "
                f"Valid values are {[e.value for e in models.BuilderVariant]}"
            )
        )
    if environment.frontend_variant not in models.FrontendVariant:
        raise errors.ValidationError(
            message=(
                f"Invalid value for the field 'frontend_variant': {environment.frontend_variant}: "
                f"Valid values are {[e.value for e in models.FrontendVariant]}"
            )
        )

    return models.UnsavedBuildParameters(
        repository=environment.repository,
        builder_variant=environment.builder_variant,
        frontend_variant=environment.frontend_variant,
        repository_revision=environment.repository_revision if environment.repository_revision else None,
        context_dir=environment.context_dir if environment.context_dir else None,
    )


def validate_build_parameters_patch(environment: apispec.BuildParametersPatch) -> models.BuildParametersPatch:
    """Validate an unsaved build parameters object."""
    if environment.builder_variant is not None and environment.builder_variant not in models.BuilderVariant:
        raise errors.ValidationError(
            message=(
                f"Invalid value for the field 'builder_variant': {environment.builder_variant}: "
                f"Valid values are {[e.value for e in models.BuilderVariant]}"
            )
        )
    if environment.frontend_variant is not None and environment.frontend_variant not in models.FrontendVariant:
        raise errors.ValidationError(
            message=(
                f"Invalid value for the field 'frontend_variant': {environment.frontend_variant}: "
                f"Valid values are {[e.value for e in models.FrontendVariant]}"
            )
        )

    return models.BuildParametersPatch(
        repository=environment.repository,
        builder_variant=environment.builder_variant,
        frontend_variant=environment.frontend_variant,
        repository_revision=environment.repository_revision,
        context_dir=environment.context_dir,
    )


def validate_environment_patch(patch: apispec.EnvironmentPatch) -> models.EnvironmentPatch:
    """Validate the update to a session environment."""
    set_fields = patch.model_fields_set

    working_directory: PurePosixPath | ResetType | None
    match patch.working_directory:
        case "":
            working_directory = RESET
        case str():
            working_directory = PurePosixPath(patch.working_directory)
        case _:
            working_directory = None

    mount_directory: PurePosixPath | ResetType | None
    match patch.mount_directory:
        case "":
            mount_directory = RESET
        case str():
            mount_directory = PurePosixPath(patch.mount_directory)
        case _:
            mount_directory = None

    command: list[str] | ResetType | None
    if "command" in set_fields and patch.command is None:
        command = RESET
    elif isinstance(patch.command, list):
        command = patch.command
    else:
        command = None

    args: list[str] | ResetType | None
    if "args" in set_fields and patch.args is None:
        args = RESET
    elif isinstance(patch.args, list):
        args = patch.args
    else:
        args = None

    return models.EnvironmentPatch(
        name=patch.name,
        description=patch.description,
        container_image=patch.container_image,
        default_url=patch.default_url,
        port=patch.port,
        working_directory=working_directory,
        mount_directory=mount_directory,
        uid=patch.uid,
        gid=patch.gid,
        args=args,
        command=command,
        is_archived=patch.is_archived,
        strip_path_prefix=patch.strip_path_prefix,
    )


def validate_environment_patch_in_launcher(patch: apispec.EnvironmentPatchInLauncher) -> models.EnvironmentPatch:
    """Validate the update to a session environment inside a session launcher."""
    environment_patch = validate_environment_patch(patch)
    environment_patch.environment_image_source = (
        None
        if patch.environment_image_source is None
        else models.EnvironmentImageSource(patch.environment_image_source.value)
    )
    environment_patch.build_parameters = (
        None if patch.build_parameters is None else validate_build_parameters_patch(patch.build_parameters)
    )
    return environment_patch


def validate_unsaved_session_launcher(
    launcher: apispec.SessionLauncherPost, builds_config: "BuildsConfig"
) -> models.UnsavedSessionLauncher:
    """Validate an unsaved session launcher."""

    environment: Union[str, models.UnsavedBuildParameters, models.UnsavedEnvironment]
    if isinstance(launcher.environment, apispec.EnvironmentIdOnlyPost):
        environment = launcher.environment.id
    elif isinstance(launcher.environment, apispec.BuildParametersPost):
        environment = validate_unsaved_build_parameters(launcher.environment, builds_config=builds_config)
    elif isinstance(launcher.environment, apispec.EnvironmentPostInLauncherHelper):
        environment_helper: apispec.EnvironmentPost = launcher.environment
        environment = validate_unsaved_environment(environment_helper, models.EnvironmentKind.CUSTOM)
    else:
        raise errors.ValidationError(message=f"Unexpected environment type: {type(launcher.environment)}")

    return models.UnsavedSessionLauncher(
        project_id=ULID.from_str(launcher.project_id),
        name=launcher.name,
        description=launcher.description,
        resource_class_id=launcher.resource_class_id,
        disk_storage=launcher.disk_storage,
        env_variables=models.EnvVar.from_apispec(launcher.env_variables) if launcher.env_variables else None,
        # NOTE: When you create an environment with a launcher the environment can only be custom
        environment=environment,
    )


def validate_session_launcher_patch(
    patch: apispec.SessionLauncherPatch, current_launcher: models.SessionLauncher, builds_config: "BuildsConfig"
) -> models.SessionLauncherPatch:
    """Validate the update to a session launcher."""
    data_dict = patch.model_dump(exclude_unset=True, mode="json")
    environment: str | models.EnvironmentPatch | models.UnsavedEnvironment | models.UnsavedBuildParameters | None = None
    if isinstance(patch.environment, apispec.EnvironmentPatchInLauncher):  # The patch is for a custom environment
        match current_launcher.environment.environment_kind, patch.environment.environment_kind:
            case models.EnvironmentKind.GLOBAL, apispec.EnvironmentKind.CUSTOM:
                # This means that the global environment is being swapped for a custom one,
                # so we have to create a brand-new environment, but we have to validate here.
                if (
                    patch.environment.environment_image_source == apispec.EnvironmentImageSourceImage.image
                    or patch.environment.environment_image_source is None
                ):
                    # NOTE: The custom environment is being created from an image.
                    validated_env = apispec.EnvironmentPostInLauncherHelper.model_validate(data_dict["environment"])
                    environment = models.UnsavedEnvironment(
                        name=validated_env.name,
                        description=validated_env.description,
                        container_image=validated_env.container_image,
                        default_url=validated_env.default_url,
                        port=validated_env.port,
                        working_directory=PurePosixPath(validated_env.working_directory)
                        if validated_env.working_directory
                        else None,
                        mount_directory=PurePosixPath(validated_env.mount_directory)
                        if validated_env.mount_directory
                        else None,
                        uid=validated_env.uid,
                        gid=validated_env.gid,
                        environment_kind=models.EnvironmentKind.CUSTOM,
                        args=validated_env.args,
                        command=validated_env.command,
                        environment_image_source=models.EnvironmentImageSource.image,
                        strip_path_prefix=validated_env.strip_path_prefix or False,
                    )
                elif patch.environment.environment_image_source == apispec.EnvironmentImageSourceBuild.build:
                    # NOTE: The environment type is changed to be built, so, all required fields should be passed (as in
                    # a POST request).
                    validated_build_parameters = apispec.BuildParameters.model_validate(
                        data_dict.get("environment", {}).get("build_parameters", {})
                    )
                    environment = validate_unsaved_build_parameters(
                        validated_build_parameters, builds_config=builds_config
                    )
            case models.EnvironmentKind.GLOBAL, None:
                # Trying to patch a global environment with a custom environment patch.
                raise errors.ValidationError(
                    message=(
                        "There are errors in the following fields, environment.environment_kind: Input should be "
                        "'custom'"
                    )
                )
            case _, apispec.EnvironmentKind.GLOBAL:
                # This means that the custom environment is being swapped for a global one, but the patch is for a
                # custom environment.
                raise errors.ValidationError(
                    message="There are errors in the following fields, environment.id: Input should be a valid string"
                )
            case models.EnvironmentKind.CUSTOM, _:
                # This means that the custom environment is being updated.
                current = current_launcher.environment.environment_image_source.value
                new = (
                    patch.environment.environment_image_source.value
                    if patch.environment.environment_image_source
                    else None
                )

                if (
                    new == "image" or (new is None and current == "image")
                ) and patch.environment.build_parameters is not None:
                    raise errors.ValidationError(
                        message="There are errors in the following fields, environment.build_parameters: Must be null"
                    )
                elif (
                    # TODO: Add a test for new == None/"build" and current == "build"
                    new == "build" or (new is None and current == "build")
                ) and patch.environment.build_parameters is None:
                    raise errors.ValidationError(
                        message="There are errors in the following fields, environment.build_parameters: Must be set"
                    )

                if current == "image" and new == "build":
                    # NOTE: We've checked that patch.environment.build_parameters is not None in the previous if block.
                    build_parameters = cast(apispec.BuildParametersPost, patch.environment.build_parameters)
                    # NOTE: The environment type is changed to be built, so, all required fields should be passed (as in
                    # a POST request). No need to get values from the current env, since they will be set by the build.
                    environment = validate_unsaved_build_parameters(build_parameters, builds_config=builds_config)
                elif current == "build" and new == "image":
                    environment = data_dict["environment"]
                    assert isinstance(environment, dict)
                    if environment.get("name") is None:  # type: ignore
                        environment["name"] = current_launcher.environment.name
                    validated_env = apispec.EnvironmentPostInLauncherHelper.model_validate(environment)
                    environment = models.UnsavedEnvironment(
                        name=validated_env.name,
                        description=validated_env.description,
                        container_image=validated_env.container_image,
                        default_url=validated_env.default_url,
                        port=validated_env.port,
                        working_directory=PurePosixPath(validated_env.working_directory)
                        if validated_env.working_directory
                        else None,
                        mount_directory=PurePosixPath(validated_env.mount_directory)
                        if validated_env.mount_directory
                        else None,
                        uid=validated_env.uid,
                        gid=validated_env.gid,
                        environment_kind=models.EnvironmentKind.CUSTOM,
                        args=validated_env.args,
                        command=validated_env.command,
                        environment_image_source=models.EnvironmentImageSource.image,
                        strip_path_prefix=validated_env.strip_path_prefix or False,
                    )
                else:
                    environment = validate_environment_patch_in_launcher(patch.environment)
    elif isinstance(patch.environment, apispec.EnvironmentIdOnlyPatch):
        environment = patch.environment.id
    resource_class_id: int | None | ResetType
    if "resource_class_id" in data_dict and data_dict["resource_class_id"] is None:
        # NOTE: This means that the resource class set in the DB should be removed so that the
        # default resource class currently set in the CRC will be used.
        resource_class_id = RESET
    else:
        resource_class_id = patch.resource_class_id
    disk_storage = RESET if "disk_storage" in data_dict and data_dict["disk_storage"] is None else patch.disk_storage
    env_variables = (
        RESET
        if "env_variables" in data_dict and (data_dict["env_variables"] is None or len(data_dict["env_variables"]) == 0)
        else models.EnvVar.from_apispec(patch.env_variables)
        if patch.env_variables
        else None
    )
    return models.SessionLauncherPatch(
        name=patch.name,
        description=patch.description,
        environment=environment,
        resource_class_id=resource_class_id,
        disk_storage=disk_storage,
        env_variables=env_variables,
    )


def validate_unsaved_build(environment_id: ULID) -> models.UnsavedBuild:
    """Validate an unsaved container image build."""
    return models.UnsavedBuild(environment_id=environment_id)


def validate_build_patch(patch: apispec.BuildPatch) -> models.BuildPatch:
    """Validate the update to a session launcher."""
    status = models.BuildStatus(patch.status.value) if patch.status else None
    return models.BuildPatch(status=status)
