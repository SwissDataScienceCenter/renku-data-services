"""Business logic for ShipWright resources."""

import logging
from typing import TYPE_CHECKING

from renku_data_services.session import constants, models
from renku_data_services.session import crs as sw_schemas
from renku_data_services.session import orm as schemas
from renku_data_services.session.k8s_client import ShipwrightClient

if TYPE_CHECKING:
    from renku_data_services.app_config.config import BuildsConfig


async def update_build_status(build: schemas.BuildORM, shipwright_client: ShipwrightClient | None) -> None:
    """Update the status of a build by pulling the corresponding BuildRun from ShipWright.

    Note: this method will update `build` in place.
    """
    if shipwright_client is None:
        logging.warning("ShipWright client not defined, BuildRun refresh skipped.")
        return

    k8s_name = build.dump().get_k8s_name()
    k8s_build = await shipwright_client.get_build_run(name=k8s_name)

    if k8s_build is None:
        build.status = models.BuildStatus.failed
    else:
        k8s_build_status = k8s_build.status
        completion_time = k8s_build_status.completionTime if k8s_build_status else None

        if k8s_build_status is None or completion_time is None:
            return

        conditions = k8s_build_status.conditions
        condition = next(filter(lambda c: c.type == "Succeeded", conditions or []), None)

        buildSpec = k8s_build_status.buildSpec
        output = buildSpec.output if buildSpec else None
        result_image = output.image if output else "unknown"

        source = buildSpec.source if buildSpec else None
        git_obj = source.git if source else None
        result_repository_url = git_obj.url if git_obj else "unknown"

        source_2 = k8s_build_status.source
        git_obj_2 = source_2.git if source_2 else None
        result_repository_git_commit_sha = git_obj_2.commitSha if git_obj_2 else None
        result_repository_git_commit_sha = result_repository_git_commit_sha or "unknown"

        if condition is not None and condition.status == "True":
            build.status = models.BuildStatus.succeeded
            build.completed_at = completion_time
            build.result_image = result_image
            build.result_repository_url = result_repository_url
            build.result_repository_git_commit_sha = result_repository_git_commit_sha
        else:
            build.status = models.BuildStatus.failed
            build.completed_at = completion_time


async def create_build(
    build: schemas.BuildORM,
    git_repository: str,
    run_image: str,
    output_image: str,
    shipwright_client: ShipwrightClient | None,
    builds_config: "BuildsConfig",
) -> None:
    """Create a new BuildRun in ShipWright to support a newly created build."""

    if shipwright_client is None:
        logging.warning("ShipWright client not defined, BuildRun creation skipped.")
    else:
        build_strategy_name = builds_config.build_strategy_name or constants.BUILD_DEFAULT_BUILD_STRATEGY_NAME
        push_secret_name = builds_config.push_secret_name or constants.BUILD_DEFAULT_PUSH_SECRET_NAME

        build_run = sw_schemas.BuildRun(
            metadata=sw_schemas.Metadata(name=build.dump().get_k8s_name()),
            spec=sw_schemas.BuildRunSpec(
                build=sw_schemas.Build(
                    spec=sw_schemas.BuildSpec(
                        source=sw_schemas.BuildSource(git=sw_schemas.Git(url=git_repository), type="Git"),
                        strategy=sw_schemas.Strategy(kind="BuildStrategy", name=build_strategy_name),
                        paramValues=[],
                        output=sw_schemas.BuildOutput(
                            image=output_image,
                            pushSecret=push_secret_name,
                        ),
                    )
                )
            ),
        )

        await shipwright_client.create_build_run(build_run)


async def cancel_build(build: schemas.BuildORM, shipwright_client: ShipwrightClient | None) -> None:
    """Cancel a build by deleting the corresponding BuildRun from ShipWright."""
    if shipwright_client is None:
        logging.warning("ShipWright client not defined, BuildRun deletion skipped.")
    else:
        await shipwright_client.delete_build_run(name=build.dump().get_k8s_name())
