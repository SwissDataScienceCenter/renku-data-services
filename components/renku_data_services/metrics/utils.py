"""Utility functions."""

import hashlib

from renku_data_services.base_models.core import APIUser


def anonymize_user_id(user: APIUser) -> str:
    """Anonymize a user's id."""
    return (
        hashlib.md5(user.id.encode("utf-8"), usedforsecurity=False).hexdigest() if user.id is not None else "anonymous"
    )
