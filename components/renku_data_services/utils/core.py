"""Shared utility functions."""
import functools
import os
import ssl


@functools.lru_cache(1)
def get_ssl_context():
    """Get an SSL context supporting mounted custom certificates."""
    context = ssl.create_default_context()
    custom_cert_folder = os.environ.get("SSL_CERT_FOLDER", None)
    if custom_cert_folder:
        context.load_verify_locations(capath=custom_cert_folder)
    return context
