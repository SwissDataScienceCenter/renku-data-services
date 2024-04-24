"""Authorization configurations."""
import os
from dataclasses import dataclass, field

from authzed.api.v1 import AsyncClient, SyncClient
from grpcutil import bearer_token_credentials, insecure_bearer_token_credentials


@dataclass
class AuthzConfig:
    """The configuration for connecting to the authorization database."""
    host: str
    grpc_port: int
    key: str = field(repr=False)
    no_tls_connection: bool = False  # If set to true it means the communication to authzed is unencrypted

    @classmethod
    def from_env(cls, prefix: str=""):
        """Create a configuration from environment variables."""
        host = os.environ[f"{prefix}AUTHZ_DB_HOST"]
        grpc_port = os.environ.get(f"{prefix}AUTHZ_DB_GRPC_PORT", "50051")
        key = os.environ[f"{prefix}AUTHZ_DB_KEY"]
        no_tls_connection = os.environ.get(f"{prefix}AUTHZ_DB_NO_TLS_CONNECTION", "false").lower() == "true"
        return cls(host, int(grpc_port), key, no_tls_connection)

    def authz_client(self) -> SyncClient:
        """Generate an Authzed client."""
        target = f"{self.host}:{self.grpc_port}"
        if self.no_tls_connection:
            credentials = insecure_bearer_token_credentials(self.key)
        else:
            credentials = bearer_token_credentials(self.key)
        return SyncClient(target=target, credentials=credentials)

    def authz_async_client(self) -> AsyncClient:
        """Generate an Authzed client."""
        target = f"{self.host}:{self.grpc_port}"
        if self.no_tls_connection:
            credentials = insecure_bearer_token_credentials(self.key)
        else:
            credentials = bearer_token_credentials(self.key)
        return AsyncClient(target=target, credentials=credentials)
