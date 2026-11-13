"""Setting up remote clusters."""

from box import Box
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from renku_data_services.app_config import logging
from renku_data_services.base_models import APIUser
from renku_data_services.crc import models
from renku_data_services.crc.db import ClusterRepository
from renku_data_services.k8s.clients import K8sClusterClientsPool
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER, ClusterId
from renku_data_services.k8s.models import K8sSecret

logger = logging.getLogger(__file__)


class RemoteClusterSetup:
    """Registers remote clusters and prepares what is needed to connect to them, such as SSH keys."""

    def __init__(self, repo: ClusterRepository, k8s_client: K8sClusterClientsPool) -> None:
        self.__repo = repo
        self.__k8s_client = k8s_client

    async def setup_remote_cluster(
        self, user: APIUser, model: models.ClusterSettings
    ) -> tuple[models.ClusterSettings, models.SshKeyPair | None]:
        """Store a new remote cluster and enable SSH access if it has SSH settings.

        Returns the saved cluster and the generated SSH keypair, or
        None when SSH is not configured.
        """

        logger.debug(f"Setting up remote cluster from settings: {model}")
        remote_cluster = await self.__repo.insert(user, model)
        kpair = (
            await self.enable_ssh_remote_cluster(model.ssh_settings, remote_cluster.id) if model.ssh_settings else None
        )
        return remote_cluster, kpair

    async def enable_ssh_remote_cluster(
        self, ssh_settings: models.SshSettings, remote_cluster_id: ClusterId
    ) -> models.SshKeyPair:
        """Enable ssh for the remote cluster.

        It generates a ssh keypair that will be used to connect to the
        remote cluster's ssh service. The remote cluster needs to add the
        public part to their authorized keys file.

        The keypair is stored in the secret named by
        `ssh_settings.auth_key_secret_name` in the namespace of the
        local (default) cluster. An existing secret is overwritten. The
        generated keypair is returned so that the public part can be
        handed to the remote cluster.
        """
        cluster = await self.__k8s_client.cluster_by_id(DEFAULT_K8S_CLUSTER)
        namespace = cluster.namespace
        kpair = generate_ssh_keypair("main-renku")
        secret_name = ssh_settings.auth_key_secret_name
        string_data = {
            str(remote_cluster_id): kpair.private_part,
        }
        secret = K8sSecret(
            name=secret_name,
            namespace=namespace,
            cluster=cluster.id,
            manifest=Box(
                {
                    "metadata": {"name": secret_name, "namespace": namespace},
                    "type": "kubernetes.io/ssh-auth",
                    "stringData": string_data,
                }
            ),
        )

        existing = await self.__k8s_client.get(secret)
        if existing is None:
            await self.__k8s_client.create(secret, refresh=False)
        else:
            # A merge patch on stringData replaces the keys in data
            await self.__k8s_client.patch(secret, {"stringData": string_data})

        return kpair


def generate_ssh_keypair(comment: str | None = None) -> models.SshKeyPair:
    """Return (private_key_openssh, public_key_openssh)."""
    private_key = ed25519.Ed25519PrivateKey.generate()

    private_openssh = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    public_openssh = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        )
        .decode()
    )

    if comment:
        public_openssh = f"{public_openssh} {comment}"

    return models.SshKeyPair(private_part=private_openssh, public_part=public_openssh)


def public_key_from_private(private_openssh: str, password: bytes | None = None, comment: str | None = None) -> str:
    """Derive the OpenSSH public key line from an OpenSSH private key."""
    private_key = serialization.load_ssh_private_key(private_openssh.encode(), password=password)

    public_openssh = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        )
        .decode()
    )

    return f"{public_openssh} {comment}" if comment else public_openssh
