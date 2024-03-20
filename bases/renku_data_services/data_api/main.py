"""The entrypoint for the data service application."""

import argparse
import asyncio
from os import environ

from sanic import Sanic
from sanic.log import logger
from sanic.worker.loader import AppLoader

from renku_data_services.app_config import Config
from renku_data_services.data_api.app import register_all_handlers
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.storage.rclone import RCloneValidator


def create_app() -> Sanic:
    """Create a Sanic application."""
    config = Config.from_env()
    app = Sanic(config.app_name)
    if "COVERAGE_RUN" in environ:
        app.config.TOUCHUP = False
        # NOTE: in single process mode where we usually run schemathesis to get coverage the db migrations
        # specified below with the main_process_start decorator do not run.
        run_migrations_for_app("common")
        config.rp_repo.initialize(config.db.conn_url(async_client=False), config.default_resource_pool)
        asyncio.run(config.kc_user_repo.initialize(config.kc_api))
    app = register_all_handlers(app, config)

    if environ.get("CORS_ALLOW_ALL_ORIGINS", "false").lower() == "true":
        from sanic_ext import Extend

        app.config.CORS_ORIGINS = "*"
        Extend(app)

    @app.main_process_start
    async def do_migrations(*_):
        logger.info("running migrations")
        run_migrations_for_app("common")
        config.rp_repo.initialize(config.db.conn_url(async_client=False), config.default_resource_pool)
        await config.kc_user_repo.initialize(config.kc_api)
        await config.group_repo.generate_user_namespaces()
        await config.event_repo.send_pending_events()

    @app.before_server_start
    async def setup_rclone_validator(app, _):
        validator = RCloneValidator()
        app.ext.dependency(validator)

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="Renku Compute Resource Access Control")
    # NOTE: K8s probes will fail if listening only on 127.0.0.1 - so we listen on 0.0.0.0
    parser.add_argument("-H", "--host", default="0.0.0.0", help="Host to listen on")  # nosec B104
    parser.add_argument("-p", "--port", default=8000, type=int, help="Port to listen on")
    parser.add_argument("--debug", action="store_true", help="Enable Sanic debug mode")
    parser.add_argument("--fast", action="store_true", help="Enable Sanic fast mode")
    parser.add_argument("-d", "--dev", action="store_true", help="Enable Sanic development mode")
    parser.add_argument("--single-process", action="store_true", help="Do not use multiprocessing.")
    args = vars(parser.parse_args())
    loader = AppLoader(factory=create_app)
    app = loader.load()
    app.prepare(**args)
    Sanic.serve(primary=app, app_loader=loader)
