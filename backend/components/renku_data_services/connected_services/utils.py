"""Utilities for connected services."""

import base64
import random


def generate_code_verifier(size: int = 48) -> str:
    """Returns a randomly generated code for use in PKCE."""
    rand = random.SystemRandom()
    return base64.b64encode(rand.randbytes(size)).decode()
