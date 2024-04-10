"""Authorization configurations."""
import os
from dataclasses import dataclass, field


@dataclass
class AuthzConfig:
    """The configuration for connecting to the authorization database."""
    host: str
    grpc_port: int
    key: str = field(repr=False)

    @classmethod
    def from_env(cls, prefix: str=""):
        """Create a configuration from environment variables."""
        host = os.environ[f"{prefix}AUTHZ_DB_HOST"]
        grpc_port = os.environ.get(f"{prefix}AUTHZ_DB_GRPC_PORT", "50051")
        key = os.environ[f"{prefix}AUTHZ_DB_KEY"]
        return cls(host, int(grpc_port), key)

