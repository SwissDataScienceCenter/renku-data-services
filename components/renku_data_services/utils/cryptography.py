"""Encryption and decryption functions."""

import base64

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


def _get_encryption_key(password: bytes, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,
    )
    return base64.urlsafe_b64encode(kdf.derive(password))


def generate_random_encryption_key() -> bytes:
    """Generate a random key to be used with Fernet encryption."""
    return Fernet.generate_key()


def encrypt_string(password: bytes, salt: str, data: str) -> bytes:
    """Encrypt a given string."""
    key = _get_encryption_key(password=password, salt=salt.encode())
    return Fernet(key).encrypt(data.encode())


def decrypt_string(password: bytes, salt: str, data: bytes) -> str:
    """Decrypt a given string."""
    key = _get_encryption_key(password=password, salt=salt.encode())
    return Fernet(key).decrypt(data).decode()


def encrypt_rsa(public_key: rsa.RSAPublicKey, data: bytes) -> bytes:
    """Encrypt with an RSA public key."""
    encrypted_data = public_key.encrypt(
        data, padding.OAEP(padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
    )
    return encrypted_data


def decrypt_rsa(private_key: rsa.RSAPrivateKey, encrypted_data: bytes) -> bytes:
    """Decrypt with an RSA private key."""
    data = private_key.decrypt(
        encrypted_data, padding.OAEP(padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
    )
    return data


def encrypt_user_secret(
    user_id: str, user_secret_key: str, secret_service_public_key: rsa.RSAPublicKey, secret_value: str
) -> tuple[bytes, bytes]:
    """Doubly encrypt a secret for a user.

    Since RSA cannot encrypt arbitrary length strings, we use symmetric encryption with a random key and encrypt the
    random key with RSA to get it to the secrets service.
    """
    # encrypt once with user secret
    encrypted_value = encrypt_string(user_secret_key.encode(), user_id, secret_value)
    # encrypt again with secret service public key
    secret_svc_encryption_key = generate_random_encryption_key()
    doubly_encrypted_value = encrypt_string(secret_svc_encryption_key, user_id, encrypted_value.decode())
    encrypted_key = encrypt_rsa(secret_service_public_key, secret_svc_encryption_key)
    return doubly_encrypted_value, encrypted_key
