"""DOI utility functions."""

import re
from urllib.parse import unquote

_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)


def parse_doi(value: str) -> str:
    """Check if a string is a valid (possibly encoded) DOI and return it in canonical form."""
    # DOI might be URL-encoded (e.g. '%2F' for '/')
    decoded_doi = unquote(value)

    if not _DOI_RE.fullmatch(decoded_doi):
        raise TypeError(f"Value is not a DOI: {value!r}")

    return decoded_doi
