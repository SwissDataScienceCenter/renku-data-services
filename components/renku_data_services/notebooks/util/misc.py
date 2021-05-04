import json
import os


def read_server_options_file():
    server_options_file = os.getenv(
        "NOTEBOOKS_SERVER_OPTIONS_PATH", "/etc/renku-notebooks/server_options.json"
    )
    with open(server_options_file) as f:
        server_options = json.load(f)

    return server_options


def read_server_options_defaults():
    options = read_server_options_file()
    output = {}
    for option_name in options.keys():
        output[option_name] = options[option_name]["default"]
    return output
