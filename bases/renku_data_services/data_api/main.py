"""The entrypoint for the data service application."""

import argparse
import asyncio
import os
from os import environ
from typing import TYPE_CHECKING, Any

import sentry_sdk
from sanic import Request, Sanic
from sanic.response import BaseHTTPResponse
from sanic.worker.loader import AppLoader
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.grpc import GRPCIntegration
from sentry_sdk.integrations.sanic import SanicIntegration, _context_enter, _context_exit, _set_transaction

import renku_data_services.solr.entity_schema as entity_schema
from renku_data_services.app_config import logging
from renku_data_services.authz.admin_sync import sync_admins_from_keycloak
from renku_data_services.base_models.core import InternalServiceAdmin, ServiceAdminId
from renku_data_services.data_api.app import register_all_handlers
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.data_api.prometheus import setup_prometheus
from renku_data_services.errors.errors import (
    ForbiddenError,
    MissingResourceError,
    UnauthorizedError,
    ValidationError,
)
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.search.reprovision import SearchReprovision
from renku_data_services.solr.solr_migrate import SchemaMigrator
from renku_data_services.storage.rclone import RCloneValidator
from renku_data_services.utils.middleware import validate_null_byte

if TYPE_CHECKING:
    import sentry_sdk._types


logger = logging.getLogger(__name__)


async def solr_reindex(reprovision: SearchReprovision) -> None:
    """Run a solr reindex of all data.

    This might be required after migrating the solr schema.
    """
    logger.info("Running SOLR reindex triggered by a migration")
    admin = InternalServiceAdmin(id=ServiceAdminId.search_reprovision)
    max_retries = 30
    i = 0
    while True:
        try:
            await reprovision.run_reprovision(admin)
        except Exception as err:
            logger.error("SOLR reindexing triggered by a migration has failed because of %s. Will wait and retry.", err)
        else:
            logger.info("SOLR reindexing triggered by a migration completed successfully")
            break
        i += 1
        if i >= max_retries:
            logger.error(f"SOLR reindexing triggered by a migration has failed {max_retries} times, giving up.")
            break
        await asyncio.sleep(10)


def create_app() -> Sanic:
    """Create a Sanic application."""
    dependency_manager = DependencyManager.from_env()
    app = Sanic(dependency_manager.app_name, configure_logging=False)

    if "COVERAGE_RUN" in environ:
        app.config.TOUCHUP = False
        # NOTE: in single process mode where we usually run schemathesis to get coverage the db migrations
        # specified below with the main_process_start decorator do not run.
        run_migrations_for_app("common")
        asyncio.run(
            dependency_manager.rp_repo.initialize(
                dependency_manager.config.db.conn_url(async_client=False), dependency_manager.default_resource_pool
            )
        )
        asyncio.run(dependency_manager.kc_user_repo.initialize(dependency_manager.kc_api))
        asyncio.run(sync_admins_from_keycloak(dependency_manager.kc_api, dependency_manager.authz))
    if dependency_manager.config.sentry.enabled:
        logger.info("enabling sentry")

        def filter_error(
            event: "sentry_sdk._types.Event", hint: "sentry_sdk._types.Hint"
        ) -> "sentry_sdk._types.Event | None":
            if "exc_info" in hint:
                exc_type, exc_value, tb = hint["exc_info"]
                if isinstance(exc_value, (MissingResourceError, UnauthorizedError, ForbiddenError, ValidationError)):
                    return None
            return event

        @app.before_server_start
        async def setup_sentry(_: Sanic) -> None:
            sentry_sdk.init(
                dsn=dependency_manager.config.sentry.dsn,
                environment=dependency_manager.config.sentry.environment,
                release=dependency_manager.config.sentry.release or None,
                integrations=[
                    AsyncioIntegration(),
                    SanicIntegration(unsampled_statuses={404, 403, 401}),
                    GRPCIntegration(),
                ],
                enable_tracing=dependency_manager.config.sentry.sample_rate > 0,
                traces_sample_rate=dependency_manager.config.sentry.sample_rate,
                before_send=filter_error,
                in_app_include=["renku_data_services"],
            )

        # we manually need to set the signals because sentry sanic integration doesn't work with using
        # an app factory. See https://github.com/getsentry/sentry-python/issues/2902
        app.signal("http.lifecycle.request")(_context_enter)
        app.signal("http.lifecycle.response")(_context_exit)
        app.signal("http.routing.after")(_set_transaction)
    if (
        dependency_manager.config.trusted_proxies.proxies_count is not None
        and dependency_manager.config.trusted_proxies.proxies_count > 0
    ):
        app.config.PROXIES_COUNT = dependency_manager.config.trusted_proxies.proxies_count
    logger.info(f"PROXIES_COUNT = {app.config.PROXIES_COUNT}")
    if dependency_manager.config.trusted_proxies.real_ip_header:
        app.config.REAL_IP_HEADER = dependency_manager.config.trusted_proxies.real_ip_header
    logger.info(f"REAL_IP_HEADER = {app.config.REAL_IP_HEADER}")

    app = register_all_handlers(app, dependency_manager)
    setup_prometheus(app)

    if environ.get("CORS_ALLOW_ALL_ORIGINS", "false").lower() == "true":
        from sanic_ext import Extend

        app.config.CORS_ORIGINS = "*"
        Extend(app)

    app.register_middleware(validate_null_byte, "request")

    @app.on_request
    async def set_request_id(request: Request) -> None:
        logging.set_request_id(str(request.id))

    @app.middleware("response")
    async def set_request_id_header(request: Request, response: BaseHTTPResponse) -> None:
        response.headers["X-Request-ID"] = request.id

    @app.middleware("response")
    async def handle_head(request: Request, response: BaseHTTPResponse) -> None:
        """Make sure HEAD requests return an empty body."""
        if request.method == "HEAD":
            response.body = None

    @app.main_process_start
    async def do_migrations(_: Sanic) -> None:
        logger.info("running migrations")
        run_migrations_for_app("common")
        await dependency_manager.rp_repo.initialize(
            dependency_manager.config.db.conn_url(async_client=False), dependency_manager.default_resource_pool
        )

    @app.main_process_start
    async def do_solr_migrations(app: Sanic) -> None:
        logger.info(f"Running SOLR migrations at: {dependency_manager.config.solr}")
        migrator = SchemaMigrator(dependency_manager.config.solr)
        await migrator.ensure_core()
        result = await migrator.migrate(entity_schema.all_migrations)
        # starting background tasks can only be done in `main_process_ready`
        app.ctx.solr_reindex = result.requires_reindex
        logger.info(f"SOLR migration done: {result}")

    @app.before_server_start
    async def setup_rclone_validator(app: Sanic) -> None:
        validator = RCloneValidator()
        app.ext.dependency(validator)

    @app.after_server_start
    async def ready(app: Sanic) -> None:
        """Application ready event handler."""
        if getattr(app.ctx, "solr_reindex", False):
            logger.info("Creating solr reindex task, as required by migrations.")
            app.add_task(solr_reindex(dependency_manager.search_reprovisioning))

    @app.before_server_start
    async def logging_setup1(app: Sanic) -> None:
        logging.configure_logging(dependency_manager.config.log_cfg)

    @app.main_process_ready
    async def logging_setup2(app: Sanic) -> None:
        logging.configure_logging(dependency_manager.config.log_cfg)

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
    args: dict[str, Any] = vars(parser.parse_args())
    loader = AppLoader(factory=create_app)
    app = loader.load()
    app.prepare(**args)
    if os.name == "posix" and args.get("single_process", False):
        Sanic.start_method = "fork"
        Sanic.serve(primary=app)
    else:
        Sanic.serve(primary=app, app_loader=loader)
