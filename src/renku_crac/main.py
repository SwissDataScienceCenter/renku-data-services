"""The entrypoint for the CRAC application."""
from sanic import Sanic

from renku_crac.app import register_all_handlers
from renku_crac.config import Config

config = Config.from_env()
app = register_all_handlers(Sanic("renku_crac"), config)
