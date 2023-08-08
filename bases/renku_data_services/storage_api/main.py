"""The entrypoint for the Cloud Storage application."""
import argparse
from os import environ

from sanic import Sanic
from sanic.log import logger
from sanic.worker.loader import AppLoader

from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.storage_api.app import register_all_handlers
from renku_data_services.storage_api.config import Config
from renku_data_services.storage_schemas.core import RCloneValidator


def create_app() -> Sanic:
    """Create a Sanic application."""
    config = Config.from_env()
    app = Sanic(config.app_name)
    if "COVERAGE_RUN" in environ:
        app.config.TOUCHUP = False
        # NOTE: in single process mode where we usually run schemathesis to get coverage the db migrations
        # specified below with the main_process_start decorator do not run.
        run_migrations_for_app("storage", config.repo)
    app = register_all_handlers(app, config)

    @app.main_process_start
    async def do_migrations(*_):
        logger.info("running migrations")
        run_migrations_for_app("storage", config.repo)

    app.ext.add_dependency(RCloneValidator)

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="Renku Cloud Storage Service")
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
