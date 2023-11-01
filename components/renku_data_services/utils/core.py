"""Shared utility functions."""
import functools
import os
import ssl
from typing import Any, Set

from deepmerge import always_merger


@functools.lru_cache(1)
def get_ssl_context():
    """Get an SSL context supporting mounted custom certificates."""
    context = ssl.create_default_context()
    custom_cert_file = os.environ.get("SSL_CERT_FILE", None)
    if custom_cert_file:
        context.load_verify_locations(cafile=custom_cert_file)
    return context


def merge_api_specs(*args):
    """Merges API spec files into a single one."""
    merged_spec: dict[str, Any]
    merged_spec = functools.reduce(always_merger.merge, list(*args), dict())

    # Remove duplicate entries in `.servers`
    server_urls: Set[str]
    server_urls = set((obj["url"] for obj in merged_spec.get("servers", [])))
    merged_spec["servers"] = [dict(url=url) for url in server_urls]

    return merged_spec
