import json
import os


def read_server_options_ui():
    server_options_file = os.getenv(
        "NOTEBOOKS_SERVER_OPTIONS_UI_PATH",
        "/etc/renku-notebooks/server_options/server_options.json",
    )
    if os.getenv("TELEPRESENCE_ROOT") is not None:
        server_options_file = os.path.join(
            os.getenv("TELEPRESENCE_ROOT"),
            server_options_file.lstrip("/"),
        )
    with open(server_options_file) as f:
        server_options = json.load(f)

    return server_options


def read_server_options_defaults():
    server_options_file = os.getenv(
        "NOTEBOOKS_SERVER_OPTIONS_DEFAULTS_PATH",
        "/etc/renku-notebooks/server_options/server_defaults.json",
    )
    if os.getenv("TELEPRESENCE_ROOT") is not None:
        server_options_file = os.path.join(
            os.getenv("TELEPRESENCE_ROOT"),
            server_options_file.lstrip("/"),
        )
    with open(server_options_file) as f:
        server_options = json.load(f)

    return server_options
