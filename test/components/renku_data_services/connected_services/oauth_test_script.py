"""A test script for real world."""

import asyncio
import http
import os
import socketserver
import threading
import urllib

from renku_data_services.app_config import logging
from renku_data_services.base_api.pagination import PaginationRequest
from renku_data_services.base_models.core import AuthenticatedAPIUser
from renku_data_services.connected_services.models import (
    OAuth2Client,
    OAuth2Connection,
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
github_client_id = os.environ.get("GITHUB_CLIENT_ID", "abc")
github_client_secret = os.environ.get("GITHUB_CLIENT_SECRET", "***")
provider_id = "github1"


### ---------------------------------------------------------------------

deps = DependencyManager.from_env()
logger = logging.getLogger(__file__)
factory = DefaultOAuthHttpClientFactory(
    deps.config.secrets.encryption_key, deps.config.db.async_session_maker, "http://localhost:9000"
)


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
        provider = await cc_repo.insert_oauth2_client(
            user,
            UnsavedOAuth2Client(
                id=provider_id,
                app_slug="myapp",
                client_id=github_client_id,
                client_secret=github_client_secret,
                display_name="github",
                scope="api read",
                url="https://github.com",
                kind=ProviderKind.github,
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
    callback_url = "http://localhost:9000"
    cc_repo = deps.connected_services_repo
    connections = await cc_repo.get_oauth2_connections(user)
    connections = [c for c in connections if c.provider_id == provider_id]
    if connections == []:
        url = await cc_repo.authorize_client(user, provider_id, callback_url)
        print(f"visit this url:\n{url}")
        (state, path) = wait_for_oauth_callback(9000, url)
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
    cc_repo = deps.connected_services_repo
    connections = await cc_repo.get_oauth2_connections(user)
    connections = [c for c in connections if c.provider_id == provider_id]
    if connections == []:
        url = await factory.create_authorization_url(user, provider_id)
        print(f"visit this url:\n{url}")
        (state, path) = wait_for_oauth_callback(9000, url)

        client = await factory.fetch_token(state, path)
        if isinstance(client, OAuthHttpFactoryError):
            raise Exception(f"Error in fetch_token code: {client}")
        return client
    else:
        if connections[0].is_connected:
            print("Connected.")
            client = await factory.for_user_connection(user, connections[0].id)
            if isinstance(client, OAuthHttpFactoryError):
                raise Exception(f"Error obtaining code: {client}")
            return client
        else:
            await cc_repo.delete_oauth2_connection(user, connections[0].id)
            return await create_connection2()


async def make_http_client(conn: OAuth2Connection) -> OAuthHttpClient:
    client_or_error = await factory.for_user_connection(user, conn.id)
    if isinstance(client_or_error, OAuthHttpFactoryError):
        raise Exception(f"Client not created: {client_or_error}")

    client: OAuthHttpClient = client_or_error
    return client


async def prepare_test() -> OAuthHttpClient:
    await create_user()
    await create_oauth_client()
    return await create_connection2()


#    return await make_http_client(conn)


async def async_main() -> None:
    client = await prepare_test()

    account = await client.get_connected_account()
    print("---------------------------------------------------------")
    print(f"Account:\n {account}")
    print(f"Authorize Url:\n {await factory.create_authorization_url(user, provider_id)}")
    token = await client.get_token()
    print(f"Token:\n {token}")
    apps = await client.get_oauth2_app_installations(PaginationRequest(page=1, per_page=10))
    print(apps)


if __name__ == "__main__":
    asyncio.run(async_main())
