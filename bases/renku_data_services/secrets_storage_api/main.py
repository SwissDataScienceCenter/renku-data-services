"""The entrypoint for the secrets storage application."""

import argparse
import asyncio
from os import environ

from sanic import Sanic
from sanic.log import logger
from sanic.worker.loader import AppLoader

from renku_data_services.secrets.config import Config
from renku_data_services.secrets_storage_api.app import register_all_handlers


def create_app() -> Sanic:
    """Create a Sanic application."""
    config = Config.from_env()
    app = Sanic(config.app_name)
    if "COVERAGE_RUN" in environ:
        app.config.TOUCHUP = False
        # NOTE: in single process mode where we usually run schemathesis to get coverage the db migrations
        # specified below with the main_process_start decorator do not run.
        asyncio.run(config.kc_user_repo.initialize(config.kc_api))
    app = register_all_handlers(app, config)

    @app.main_process_start
    async def do_migrations(*_):
        logger.info("running migrations")
        config.rp_repo.initialize(config.db.conn_url(async_client=False), config.default_resource_pool)
        await config.kc_user_repo.initialize(config.kc_api)

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="Renku Secrets Storage")
    # NOTE: K8s probes will fail if listening only on 127.0.0.1 - so we listen on 0.0.0.0
    parser.add_argument("-H", "--host", default="0.0.0.0", help="Host to listen on")  # nosec B104
    parser.add_argument("-p", "--port", default=8100, type=int, help="Port to listen on")
    parser.add_argument("--debug", action="store_true", help="Enable Sanic debug mode")
    parser.add_argument("--fast", action="store_true", help="Enable Sanic fast mode")
    parser.add_argument("-d", "--dev", action="store_true", help="Enable Sanic development mode")
    parser.add_argument("--single-process", action="store_true", help="Do not use multiprocessing.")
    args = vars(parser.parse_args())
    loader = AppLoader(factory=create_app)
    app = loader.load()
    app.prepare(**args)
    Sanic.serve(primary=app, app_loader=loader)
