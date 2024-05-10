"""Repository utilities."""

import logging
from typing import Any, Optional

import requests


def get_status(server_name: str, access_token: Optional[str]) -> dict[str, Any]:
    """Get repository status from the sidecar."""
    from renku_notebooks.config import config

    hostname = config.sessions.ingress.host
    url = f"https://{hostname}/sessions/{server_name}/sidecar/jsonrpc"

    headers = {
        "Content-Type": "application/json",
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    try:
        response = requests.post(
            url=url,
            json={"jsonrpc": "2.0", "id": 0, "method": "git/get_status"},
            headers=headers,
        )
        response.raise_for_status()
    except requests.HTTPError as e:
        logging.warning(
            f"RPC call to get git status at {url} from "
            f"the k8s API failed with status code: {getattr(e.response, 'status_code', None)} "
            f"and error: {e}"
        )
    except requests.RequestException as e:
        logging.warning(f"RPC sidecar at {url} cannot be reached: {e}")
    except Exception as e:
        logging.warning(f"Cannot get git status for {server_name}: {e}")
    else:
        return response.json().get("result", {})
