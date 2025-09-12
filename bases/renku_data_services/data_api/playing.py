"""Just playing around."""

import asyncio
import os

from sqlalchemy import select

from renku_data_services.base_models.core import APIUser
from renku_data_services.connected_services import orm as schemas
from renku_data_services.connected_services.apispec import ProviderKind
from renku_data_services.connected_services.orm import OAuth2ClientORM, OAuth2ConnectionORM
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.notebooks.api.classes.image import Image

deps = DependencyManager.from_env()


async def create_user(id: str, fname: str, lname: str, admin: bool) -> None:
    """Create a user."""
    api_user = APIUser(id=id, is_admin=admin, first_name=fname, last_name=lname)
    await deps.kc_user_repo.get_or_create_user(requested_by=api_user, id=id)


admin = APIUser(
    id="16ad1834-0e94-4b68-8d6d-f39961ff555d",
    is_admin=True,
    first_name="Armin",
    last_name="A",
    access_token="blabla",  # nosec
)


async def create_test_users() -> None:
    """Create my test users."""
    await create_user("46ee17f0-e689-47d8-9747-5517f1f8440f", "Eike", "K", False)
    await create_user("77b45c0a-7e3c-400c-a0cf-8bcd1dc0e53f", "James", "B", False)
    await create_user("16ad1834-0e94-4b68-8d6d-f39961ff555d", "Armin", "A.", True)


async def gh_image_token(gh_token: str) -> None:
    """Bla."""
    gh_name = "ghcr.io/eikek/privim"
    gh_image = Image.from_path(gh_name)
    reg_api = gh_image.repo_api().with_oauth2_token(gh_token)
    token = await reg_api._get_docker_token(gh_image)
    print(token)


async def gl_image_token(gl_token: str) -> None:
    """Bla."""
    gl_name = "registry.gitlab.com/eikek1/privim"
    gl_image = Image.from_path(gl_name)
    #    token = base64.b64encode(f"eikek1:{gl_token}".encode()).decode()
    #    print(token)
    reg_api = gl_image.repo_api().with_oauth2_token(gl_token).with_oauth2_user("eikek1")
    token = await reg_api._get_docker_token(gl_image)
    print(token)


async def dh_image_token() -> None:
    """Bla."""
    dh_name = "docspell/restserver"
    dh_image = Image.from_path(dh_name)
    reg_api = dh_image.repo_api()  # .with_oauth2_token(gh_token)
    token = await reg_api._get_docker_token(dh_image)
    print(token)


async def check_image(image_name: str, token: str | None, user: str | None) -> None:
    """Bla."""
    image = Image.from_path(image_name)

    reg_api, conn_id = await deps.connected_services_repo.get_docker_client(admin, image)

    if reg_api is None:
        print("Using public registry api…")
        reg_api = image.repo_api()
        reg_api = reg_api.with_oauth2_token(token) if token is not None else reg_api
        reg_api = reg_api.with_oauth2_user(user) if user is not None else reg_api

    result = await reg_api.image_check(image)
    print(f"{image_name}: {result}")


async def check_docker_image(gh_token: str, gl_token: str) -> None:
    """The bla."""

    # dockerhub always reports 401 for non existent images
    # await check_image("docspell/restserver", None, None)
    await check_image("eikek0/privim2", "", None)

    # github uses 404 for non existent
    # await check_image("ghcr.io/eikek/privim", gl_token, None)
    # await check_image("registry.gitlab.com/eikek/privim", gl_token, "eikek1")


async def db_query(image: Image) -> tuple[OAuth2ClientORM, OAuth2ConnectionORM | None] | None:
    """Bla."""
    supported_image_registry_providers = {ProviderKind.gitlab, ProviderKind.github}
    registry_urls = [f"http://{image.hostname}", f"https://{image.hostname}"]
    async with deps.config.db.async_session_maker() as session:
        stmt = (
            select(schemas.OAuth2ClientORM, schemas.OAuth2ConnectionORM)
            .join(
                schemas.OAuth2ConnectionORM,
                schemas.OAuth2ConnectionORM.client_id == schemas.OAuth2ClientORM.id,
                isouter=True,
            )  # isouter is a left-join, not an outer join
            .where(schemas.OAuth2ClientORM.image_registry_url.in_(registry_urls))
            .where(schemas.OAuth2ClientORM.kind.in_(supported_image_registry_providers))
            .limit(1)  # there could be multiple matching - just take the first arbitrary 🤷
        )
        print(stmt)
        result = await session.execute(stmt)
        row = result.one_or_none()
        if row is None or row.OAuth2ClientORM is None:
            return None
        else:
            return (row.OAuth2ClientORM, row.OAuth2ConnectionORM)


## method:

if __name__ == "__main__":
    gh_token = os.getenv("GHCR_TOKEN") or ""
    gl_token = os.getenv("GLAB_TOKEN") or ""
    img1 = "ghcr.io/eikek/privim"
    img2 = "gitlab-registry.datascience.ch/eike/privim"
    image = Image.from_path(img2)
    result = asyncio.run(db_query(image))
    print(result)
#    asyncio.run(check_docker_image(gh_token, gl_token))
