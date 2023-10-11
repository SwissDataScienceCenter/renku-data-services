"""Shared utility functions."""
import ssl


def get_ssl_context():
    """Get an SSL context supporting mounted custom certificates."""
    context = ssl.create_default_context()
    context.load_verify_locations(capath="/usr/local/share/ca-certificates")
    return context
