"""The entrypoint for the CRC application."""
import argparse
from os import environ, getpid

from prometheus_client import generate_latest, multiprocess, CollectorRegistry

from sanic import Sanic
from sanic.response import HTTPResponse
from sanic.worker.loader import AppLoader

from renku_crc.app import register_all_handlers
from renku_crc.config import Config

environ["prometheus_multiproc_dir"] = "/tmp/prometheus_multiproc_dir"

def create_app() -> Sanic:
    """Create a Sanic application."""
    config = Config.from_env()
    app = Sanic(config.app_name)
    if "COVERAGE_RUN" in environ:
        app.config.TOUCHUP = False
        # NOTE: in single process mode where we usually run schemathesis to get coverage the db migrations
        # specified below with the main_process_start decorator do not run.
        config.rp_repo.do_migrations()
        config.user_repo.do_migrations()
        config.rp_repo.initialize(config.default_resource_pool)
    app = register_all_handlers(app, config)

    @app.main_process_start
    async def do_migrations(*_):
        config.rp_repo.do_migrations()
        config.user_repo.do_migrations()
        config.rp_repo.initialize(config.default_resource_pool)

    @app.route('/metrics')
    async def get_metrics(request):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        metrics = generate_latest(registry)
        return HTTPResponse(metrics, headers={"Content-Type": "text/plain; version=0.0.4; charset=utf-8"})

    @app.before_server_stop
    async def cleanup_metrics(app, _):
        multiprocess.mark_process_dead(getpid())

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
