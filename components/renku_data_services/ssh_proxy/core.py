"""Business logic for ssh proxy."""

from renku_data_services import errors
from renku_data_services.app_config import logging
from renku_data_services.crc.db import ClusterRepository
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER
from renku_data_services.k8s.models import K8sObject, K8sObjectFilter
from renku_data_services.notebooks.constants import AMALTHEA_SESSION_GVK
from renku_data_services.resource_usage.core import K8sClient
from renku_data_services.ssh_proxy.model import SshSessionData
from renku_data_services.users.core import fingerprint_ssh_public_key
from renku_data_services.users.db import SSHKeyRepository

logger = logging.getLogger(__file__)


class SessionAuthorize:
    """Provides methods to check ssh access to sessions."""

    def __init__(self, ssh_key_repo: SSHKeyRepository, k8s_client: K8sClient, cluster_repo: ClusterRepository) -> None:
        self.__ssh_key_repo = ssh_key_repo
        self.__k8s_client = k8s_client
        self.__cluster_repo = cluster_repo

    async def authorize_session(self, public_key: str, session_id: str) -> SshSessionData:
        """Authorize a session name."""
        fingerprint = fingerprint_ssh_public_key(public_key)
        logger.debug(f"Authorize public key for ssh access: {fingerprint}")
        user_id = await self.__ssh_key_repo.get_user_id_by_fingerprint(fingerprint) if fingerprint else None
        if user_id is None:
            # NOTE: malformed and unknown keys are both a plain "no", so the proxy has one failure branch.
            raise errors.MissingResourceError(message="No registered SSH key matches the provided key.")
        sessions = [
            obj
            async for obj in self.__k8s_client.list(
                K8sObjectFilter(gvk=AMALTHEA_SESSION_GVK, name=session_id, user_id=user_id)
            )
        ]
        if not sessions:
            raise errors.MissingResourceError(message="The session does not exist or is not accessible.")

        return await self.__session_data(sessions[0], session_id)

    async def __session_data(self, session: K8sObject, session_id: str) -> SshSessionData:
        """Point the proxy at the remote cluster's ssh service if the session runs on one."""
        if session.cluster == DEFAULT_K8S_CLUSTER:
            return SshSessionData.default(session_id)

        cluster = await self.__cluster_repo.select(session.cluster)
        if cluster.ssh_settings is None:
            return SshSessionData.default(session_id)

        ssh_settings = cluster.ssh_settings
        logger.info(f"Session {session_id} is on remote cluster {cluster.id}, targeting {ssh_settings.target_host}")
        return SshSessionData(
            target_host=ssh_settings.target_host,
            target_port=ssh_settings.target_port,
            target_user=session_id,
            host_key_pub=ssh_settings.public_host_key,
            auth_key_priv=str(cluster.id),
        )
