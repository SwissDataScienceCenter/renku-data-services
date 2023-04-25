"""The entrypoint for the CRAC application."""
import argparse

from sanic import Sanic
from sanic.worker.loader import AppLoader

from src.renku_crac.app import Server
from src.renku_crac.config import Config


def create_app() -> Sanic:
    """Create a Sanic application."""
    config = Config.from_env()
    app = Sanic(config.app_name)
    server = Server(config)
    server.register_handlers(app)
    
    @app.main_process_start
    async def do_migrations(*_):
        config.db.do_migrations()

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="Renku Compute Resource Access Control")
    parser.add_argument("-H", "--host", default="0.0.0.0", help="Host to listen on")
    parser.add_argument("-p", "--port", default=8000, type=int, help="Port to listen on")
    parser.add_argument("--debug", action="store_true", help="Enable Sanic debug mode")
    parser.add_argument("--fast", action="store_true", help="Enable Sanic fast mode")
    parser.add_argument("-d", "--dev", action="store_true", help="Enable Sanic development mode")
    args = parser.parse_args()
    loader = AppLoader(factory=create_app)
    app = loader.load()
    app.prepare(**vars(args))
    Sanic.serve(primary=app, app_loader=loader)
