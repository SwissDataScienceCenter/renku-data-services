"""Configurations."""

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes

from renku_data_services import errors


@dataclass
class PublicSecretsConfig:
    """Configuration class for secrets settings."""

    public_key: rsa.RSAPublicKey
    encryption_key: bytes = field(repr=False)

    @classmethod
    def from_env(cls) -> Self:
        """Load config from environment variables."""
        if os.environ.get("DUMMY_STORES", "false").lower() == "true":
            public_key_path = os.getenv("SECRETS_SERVICE_PUBLIC_KEY_PATH")
            encryption_key = secrets.token_bytes(32)
            if public_key_path is not None:
                public_key = serialization.load_pem_public_key(Path(public_key_path).read_bytes())
            else:
                # generate new random key
                private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
                public_key = private_key.public_key()
        else:
            public_key_path = os.getenv("SECRETS_SERVICE_PUBLIC_KEY_PATH", "/secret_service_public_key")
            encryption_key_path = os.getenv("ENCRYPTION_KEY_PATH", "encryption_key")
            encryption_key = Path(encryption_key_path).read_bytes()
            public_key_path = os.getenv("SECRETS_SERVICE_PUBLIC_KEY_PATH", "/secret_service_public_key")
            public_key = serialization.load_pem_public_key(Path(public_key_path).read_bytes())
        if not isinstance(public_key, rsa.RSAPublicKey):
            raise errors.ConfigurationError(message="Secret service public key is not an RSAPublicKey")

        return cls(
            public_key=public_key,
            encryption_key=encryption_key,
        )


@dataclass
class PrivateSecretsConfig:
    """Private configuration for the secrets service.

    IMPORTANT: To only be used inside secrets service.
    """

    private_key: rsa.RSAPrivateKey
    previous_private_key: rsa.RSAPrivateKey | None

    @classmethod
    def from_env(cls) -> Self:
        """Load config from environment."""
        previous_private_key: PrivateKeyTypes | None = None
        if os.environ.get("DUMMY_STORES", "false").lower() == "true":
            private_key_path = os.getenv("SECRETS_SERVICE_PRIVATE_KEY_PATH")
            if private_key_path:
                private_key = serialization.load_pem_private_key(Path(private_key_path).read_bytes(), password=None)
            else:
                private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            previous_secrets_service_private_key_path = os.getenv("PREVIOUS_SECRETS_SERVICE_PRIVATE_KEY_PATH")
            if previous_secrets_service_private_key_path:
                previous_private_key_content = Path(previous_secrets_service_private_key_path).read_bytes()
                if previous_private_key_content is not None and len(previous_private_key_content) > 0:
                    previous_private_key = serialization.load_pem_private_key(
                        previous_private_key_content, password=None
                    )
        else:
            private_key_path = os.getenv("SECRETS_SERVICE_PRIVATE_KEY_PATH", "/secrets_service_private_key")
            private_key = serialization.load_pem_private_key(Path(private_key_path).read_bytes(), password=None)
            previous_secrets_service_private_key_path = os.getenv("PREVIOUS_SECRETS_SERVICE_PRIVATE_KEY_PATH")
            if previous_secrets_service_private_key_path and Path(previous_secrets_service_private_key_path).exists():
                previous_private_key = serialization.load_pem_private_key(
                    Path(previous_secrets_service_private_key_path).read_bytes(), password=None
                )
        if not isinstance(private_key, rsa.RSAPrivateKey):
            raise errors.ConfigurationError(message="Secret service private key is not an RSAPrivateKey")

        if previous_private_key is not None and not isinstance(previous_private_key, rsa.RSAPrivateKey):
            raise errors.ConfigurationError(message="Old secret service private key is not an RSAPrivateKey")

        return cls(private_key=private_key, previous_private_key=previous_private_key)
