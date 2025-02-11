"""Business logic for ShipWright resources."""

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from box import Box

from renku_data_services.session import constants, models
from renku_data_services.session import orm as schemas
from renku_data_services.session import shipwright_crs as sw_schemas
from renku_data_services.session.shipwright_client import ShipwrightClient

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
    k8s_build = await shipwright_client.get_build_run_raw(name=k8s_name)

    if k8s_build is None:
        build.status = models.BuildStatus.failed
    else:
        completion_time_str: str | None = k8s_build.status.get("completionTime")
        completion_time = datetime.fromisoformat(completion_time_str) if completion_time_str else None

        if completion_time is None:
            return

        conditions: list[Box] | None = k8s_build.status.get("conditions")
        condition: Box | None = next(filter(lambda c: c.get("type") == "Succeeded", conditions or []), None)

        buildSpec: Box = k8s_build.status.get("buildSpec", Box())
        output: Box = buildSpec.get("output", Box())
        result_image: str = output.get("image", "unknown")

        source: Box = buildSpec.get("source", Box())
        git_obj: Box = source.get("git", Box())
        result_repository_url: str = git_obj.get("url", "unknown")

        source_2: Box = k8s_build.status.get("source", Box())
        git_obj_2: Box = source_2.get("git", Box())
        result_repository_git_commit_sha: str = git_obj_2.get("commitSha", "unknown")

        if condition is not None and condition.get("status") == "True":
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

        await shipwright_client.create_build_run(
            sw_schemas.BuildRun(
                metadata=sw_schemas.Metadata(name=build.dump().get_k8s_name()),
                spec=sw_schemas.BuildRunSpec(
                    build=sw_schemas.InlineBuild(
                        spec=sw_schemas.BuildSpec(
                            source=sw_schemas.GitSource(git=sw_schemas.GitRef(url=git_repository)),
                            strategy=sw_schemas.StrategyRef(kind="BuildStrategy", name=build_strategy_name),
                            paramValues=[sw_schemas.ParamValue(name="run-image", value=run_image)],
                            output=sw_schemas.BuildOutput(
                                image=output_image,
                                pushSecret=push_secret_name,
                            ),
                        )
                    )
                ),
            )
        )


async def cancel_build(build: schemas.BuildORM, shipwright_client: ShipwrightClient | None) -> None:
    """Cancel a build by deleting the corresponding BuildRun from ShipWright."""
    if shipwright_client is None:
        logging.warning("ShipWright client not defined, BuildRun deletion skipped.")
    else:
        await shipwright_client.delete_build_run(name=build.dump().get_k8s_name())
