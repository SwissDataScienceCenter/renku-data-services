"""The entrypoint for the CRAC application."""
from sanic import Sanic

from src.renku_crac.app import Server
from src.renku_crac.config import Config

app = Sanic("renku_crac")
app = Server(Config.from_env()).register_handlers(app)
