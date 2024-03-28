"""Encryption and decryption functions."""

import base64

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy import MetaData

metadata_obj = MetaData(schema="secrets")  # Has to match alembic ini section name


def _get_encryption_key(password: bytes, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,
    )
    return base64.urlsafe_b64encode(kdf.derive(password))


def encrypt_string(password: bytes, salt: str, data: str) -> str:
    """Encrypt a given string."""
    key = _get_encryption_key(password=password, salt=salt.encode())
    return Fernet(key).encrypt(data.encode()).decode()


def decrypt_string(password: bytes, salt: str, data: str) -> str:
    """Decrypt a given string."""
    key = _get_encryption_key(password=password, salt=salt.encode())
    return Fernet(key).decrypt(data.encode()).decode()
