"""A test script for real world."""

import asyncio
import http
import os
import socketserver
import threading
import urllib
from typing import Any
from urllib.parse import urlparse

from renku_data_services.app_config import logging
from renku_data_services.base_models.core import AuthenticatedAPIUser
from renku_data_services.connected_services.models import (
    OAuth2Client,
    OAuth2Connection,
    OAuth2TokenSet,
    ProviderKind,
    UnsavedOAuth2Client,
)
from renku_data_services.connected_services.oauth_http import (
    DefaultOAuthHttpClientFactory,
    OAuthHttpClient,
    OAuthHttpFactoryError,
)
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.errors import errors
from renku_data_services.users.db import UserInfo

# Some data to play with
user = AuthenticatedAPIUser(
    id="4c35d0bd-0ea9-431a-8e5e-7dc7ed298d8e",
    first_name="John",
    last_name="Doe",
    email="j.doe@doe.com",
    is_admin=True,
    access_token="abc",
)
# create a github app and put client_id+secret as env vars
config = {
    "gitlab": {
        "id": "gitlab-1",
        "client_id": os.environ.get("GITLAB_CLIENT_ID"),
        "client_secret": os.environ.get("GITLAB_CLIENT_SECRET"),
        "scope": "api read_api read_user",
        "url": "https://gitlab.ethz.ch",
        "kind": ProviderKind.gitlab,
    },
    "github": {
        "id": "github-1",
        "client_id": os.environ.get("GITHUB_CLIENT_ID"),
        "client_secret": os.environ.get("GITHUB_CLIENT_SECRET"),
        "scope": "api read",
        "url": "https://github.com",
        "kind": ProviderKind.github,
    },
    "provider": "gitlab",
    "callback_url": "http://localhost:9000",
}

test_provider = config[config["provider"]]
provider_id: str = test_provider["id"]

### ---------------------------------------------------------------------

deps = DependencyManager.from_env()
logger = logging.getLogger(__file__)
factory = DefaultOAuthHttpClientFactory(deps.config.secrets.encryption_key, deps.config.db.async_session_maker)


async def create_user() -> UserInfo:
    user_db = deps.kc_user_repo
    result = await user_db.get_or_create_user(user, user.id)
    if result is None:
        raise Exception("user could not be created")
    logger.info(f"Created user {user.id}")
    return result


async def create_oauth_client() -> OAuth2Client:
    cc_repo = deps.connected_services_repo
    try:
        provider = await cc_repo.get_oauth2_client(provider_id, user)
    except errors.MissingResourceError:
        if not test_provider["client_id"]:  # type:ignore
            raise Exception("Needs a client id as env var!") from None
        if not test_provider["client_secret"]:  # type:ignore
            raise Exception("Needs a client secret as env var!") from None
        provider = await cc_repo.insert_oauth2_client(
            user,
            UnsavedOAuth2Client(
                id=provider_id,
                app_slug="myapp",
                client_id=test_provider["client_id"],  # type:ignore
                client_secret=test_provider["client_secret"],  # type:ignore
                display_name=provider_id,  # type:ignore
                scope=test_provider["scope"],  # type:ignore
                url=test_provider["url"],  # type:ignore
                kind=test_provider["kind"],  # type:ignore
                use_pkce=False,
            ),
        )
    logger.info(f"OAuth2 Provider exsists: {provider.id}/{provider.kind}")
    return provider


def wait_for_oauth_callback(port: int, url: str) -> (str, str):
    state: str = ""
    path: str = ""

    class CallbackHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            nonlocal state
            nonlocal path

            query_data = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            path = self.path
            state = query_data.get("state")

            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OAuth callback received. You can close this window.")

            # signal the server to shut down (must be run in a separate thread)
            shutdown_thread = threading.Thread(target=self.server.shutdown)
            shutdown_thread.start()

    with socketserver.TCPServer(("", port), CallbackHandler) as httpd:
        httpd.serve_forever()  # won't actually run forever

    logger.info(f"Got authorize callback state: {state[0]}. Getting token.")
    return (state[0], path)


async def create_connection() -> OAuth2Connection:
    callback_url: str = config["callback_url"]
    port = urlparse(callback_url).port or 9000
    cc_repo = deps.connected_services_repo
    connections = await cc_repo.get_oauth2_connections(user)
    connections = [c for c in connections if c.provider_id == provider_id]
    if connections == []:
        url = await cc_repo.authorize_client(user, provider_id, callback_url)
        print(f"visit this url:\n{url}")
        (state, path) = wait_for_oauth_callback(port, url)
        await cc_repo.authorize_callback(state, path, callback_url)
        return await create_connection()
    else:
        if connections[0].is_connected:
            print("Connected.")
            return connections[0]
        else:
            await cc_repo.delete_oauth2_connection(user, connections[0].id)
            return await create_connection()


async def create_connection2() -> OAuthHttpClient:
    callback_url: str = config["callback_url"]
    port = urlparse(callback_url).port or 9000
    cc_repo = deps.connected_services_repo
    connections = await cc_repo.get_oauth2_connections(user)
    connections = [c for c in connections if c.provider_id == provider_id]
    if connections == []:
        url = await factory.initiate_oauth_flow(user, provider_id, callback_url)
        print(f"visit this url:\n{url}")
        (state, path) = wait_for_oauth_callback(port, url)

        client = await factory.fetch_token(state, path, callback_url)
        if isinstance(client, OAuthHttpFactoryError):
            raise Exception(f"Error in fetch_token code: {client}")
        return client
    else:
        if connections[0].is_connected:
            print("Connected.")
            client = await factory.for_user_connection(user, connections[0].id)
            if isinstance(client, OAuthHttpFactoryError):
                raise Exception(f"Error getting client for user: {client}")
            return client
        else:
            logger.info(f"Connection {connections[0].id} exists, but is not in connected state")
            await cc_repo.delete_oauth2_connection(user, connections[0].id)
            return await create_connection2()


async def make_http_client(conn: OAuth2Connection) -> OAuthHttpClient:
    client_or_error = await factory.for_user_connection(user, conn.id, config["callback_url"])
    if isinstance(client_or_error, OAuthHttpFactoryError):
        raise Exception(f"Client not created: {client_or_error}")

    client: OAuthHttpClient = client_or_error
    return client


def set_refresh_token(token: dict[str, Any], plain_refresh_token: str) -> OAuth2TokenSet:
    token["refresh_token"] = plain_refresh_token
    token["expires_at"] = 1  # must be >0 because python treas 0 as False and skips checks then
    token["expires_in"] = 1
    return factory.encrypt_token_set(token, user.id)


def set_token_expired(token: dict[str, Any]) -> OAuth2TokenSet:
    token["expires_at"] = 1  # must be >0 because python treas 0 as False and skips checks then
    token["expires_in"] = 1
    return factory.encrypt_token_set(token, user.id)


async def store_token(token: OAuth2TokenSet, client: OAuthHttpClient) -> None:
    conn = client.connection
    async with deps.config.db.async_session_maker() as session, session.begin():
        session.add(conn)
        conn.token = token
        await session.flush()


async def prepare_test() -> OAuthHttpClient:
    await create_user()
    await create_oauth_client()
    return await create_connection2()


async def replay_stale_read() -> None:
    # start with no connection row, this test taints it
    client = await prepare_test()
    token = await client.get_token()
    await store_token(set_token_expired(token), client)

    client = await create_connection2()
    client2 = await create_connection2()

    print("Try to refresh with two clients")

    result = await client.get_connected_account()
    print(result)  # this works
    result = await client2.get_connected_account()
    print(result)  # this crashes


async def async_main() -> None:
    # client = await create_connection2()
    # token = await client.get_token()
    # print(token)
    await replay_stale_read()


if __name__ == "__main__":
    asyncio.run(async_main())
