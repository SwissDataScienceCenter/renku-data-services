"""The entrypoint for the secrets storage application."""

import argparse
import os
from multiprocessing import Lock
from os import environ
from typing import Any

from prometheus_sanic import monitor
from sanic import Request, Sanic
from sanic.response import BaseHTTPResponse
from sanic.worker.loader import AppLoader

from renku_data_services.app_config import logging
from renku_data_services.base_models.core import InternalServiceAdmin, ServiceAdminId
from renku_data_services.secrets_storage_api.app import register_all_handlers
from renku_data_services.secrets_storage_api.dependencies import DependencyManager


def create_app() -> Sanic:
    """Create a Sanic application."""
    dm = DependencyManager.from_env()
    app = Sanic(dm.config.app_name)
    if "COVERAGE_RUN" in environ:
        app.config.TOUCHUP = False
    app = register_all_handlers(app, dm)

    @app.on_request
    async def set_request_id(request: Request) -> None:
        logging.set_request_id(str(request.id))

    @app.middleware("response")
    async def set_request_id_header(request: Request, response: BaseHTTPResponse) -> None:
        response.headers["X-Request-ID"] = request.id

    @app.main_process_start
    def main_process_start(app: Sanic) -> None:
        app.shared_ctx.rotation_lock = Lock()
        logging.configure_logging(dm.config.log_cfg)

    @app.before_server_start
    async def logging_setup1(app: Sanic) -> None:
        logging.configure_logging(dm.config.log_cfg)

    # Setup prometheus
    monitor(app, endpoint_type="url", multiprocess_mode="all", is_middleware=True).expose_endpoint()

    async def rotate_encryption_key_listener(app: Sanic) -> None:
        """Rotate RSA private key."""
        if dm.config.secrets.previous_private_key is None:
            return

        lock = app.shared_ctx.rotation_lock.acquire(block=False)

        if not lock:
            return  # only run rotation on one worker

        try:
            await dm.user_secrets_repo.rotate_encryption_keys(
                InternalServiceAdmin(id=ServiceAdminId.secrets_rotation),
                dm.config.secrets.private_key,
                dm.config.secrets.previous_private_key,
            )
        finally:
            app.shared_ctx.rotation_lock.release()

    app.register_listener(rotate_encryption_key_listener, "after_server_start")

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="Renku Secrets Storage")
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
