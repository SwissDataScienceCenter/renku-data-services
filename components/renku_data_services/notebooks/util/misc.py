import json
import os


def read_server_options_ui():
    server_options_file = os.getenv(
        "NOTEBOOKS_SERVER_OPTIONS_UI_PATH",
        "/etc/renku-notebooks/server_options/server_options.json",
    )
    with open(server_options_file) as f:
        server_options = json.load(f)

    return server_options


def read_server_options_defaults():
    server_options_file = os.getenv(
        "NOTEBOOKS_SERVER_OPTIONS_DEFAULTS_PATH",
        "/etc/renku-notebooks/server_options/server_defaults.json",
    )
    with open(server_options_file) as f:
        server_options = json.load(f)

    return server_options
