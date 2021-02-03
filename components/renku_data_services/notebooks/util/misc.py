import json
import os


def read_server_options_file():
    server_options_file = os.getenv(
        "NOTEBOOKS_SERVER_OPTIONS_PATH", "/etc/renku-notebooks/server_options.json"
    )
    with open(server_options_file) as f:
        server_options = json.load(f)
    return server_options
