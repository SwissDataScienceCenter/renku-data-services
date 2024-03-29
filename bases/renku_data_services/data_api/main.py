"""The entrypoint for the data service application."""

import argparse
import asyncio
from os import environ

import sentry_sdk
from prometheus_sanic import monitor
from sanic import Sanic
from sanic.log import logger
from sanic.worker.loader import AppLoader
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.sanic import SanicIntegration, _hub_enter, _hub_exit, _set_transaction

from renku_data_services.app_config import Config
from renku_data_services.data_api.app import register_all_handlers
from renku_data_services.errors.errors import (
    MissingResourceError,
    NoDefaultPoolAccessError,
    Unauthorized,
    ValidationError,
)
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
    if config.sentry.enabled:
        logger.info("enabling sentry")

        def filter_error(event, hint):
            if "exc_info" in hint:
                exc_type, exc_value, tb = hint["exc_info"]
                if isinstance(
                    exc_value, (MissingResourceError, Unauthorized, ValidationError, NoDefaultPoolAccessError)
                ):
                    return None
            return event

        @app.before_server_start
        async def setup_sentry(_):
            sentry_sdk.init(
                dsn=config.sentry.dsn,
                environment=config.sentry.environment,
                integrations=[AsyncioIntegration(), SanicIntegration(unsampled_statuses={404, 403, 401})],
                enable_tracing=config.sentry.sample_rate > 0,
                traces_sample_rate=config.sentry.sample_rate,
                before_send=filter_error,
            )

        # we manually need to set the signals because sentry sanic integration doesn't work with using
        # an app factory. See https://github.com/getsentry/sentry-python/issues/2902
        app.signal("http.lifecycle.request")(_hub_enter)
        app.signal("http.lifecycle.response")(_hub_exit)
        app.signal("http.routing.after")(_set_transaction)

    app = register_all_handlers(app, config)
    monitor(app, endpoint_type="url", multiprocess_mode="all", is_middleware=True).expose_endpoint()

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

    async def send_pending_events(app):
        """Send pending messages in case sending in a handler failed."""
        while True:
            try:
                await asyncio.sleep(30)
                await config.event_repo.send_pending_events()
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning(f"Background task failed: {e}")

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="Renku Data Services")
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
