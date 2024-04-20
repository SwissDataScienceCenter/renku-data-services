"""Authorization configurations."""
import os
from dataclasses import dataclass, field

from authzed.api.v1 import Client

# NOTE: we use insecure below because we do not use an encrypted (i.e. with SSL) connection to talk
# to the authorization service. None of the cluster-internal communication in Renku and we terminate
# SSL connections from ingress as soon as they enter our cluster.
from grpcutil import insecure_bearer_token_credentials


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

    def authz_client(self) -> Client:
        """Generate an Authzed client."""
        target = f"{self.host}:{self.grpc_port}"
        credentials = insecure_bearer_token_credentials(self.key)
        return Client(target=target, credentials=credentials)

