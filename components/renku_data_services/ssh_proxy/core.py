"""Business logic for ssh proxy."""

from renku_data_services import errors
from renku_data_services.app_config import logging
from renku_data_services.k8s.models import K8sObjectFilter
from renku_data_services.notebooks.constants import AMALTHEA_SESSION_GVK
from renku_data_services.resource_usage.core import K8sClient
from renku_data_services.ssh_proxy.model import SshSessionData
from renku_data_services.users.core import fingerprint_ssh_public_key
from renku_data_services.users.db import SSHKeyRepository

logger = logging.getLogger(__file__)


class SessionAuthorize:
    """Provides methods to check ssh access to sessions."""

    def __init__(self, ssh_key_repo: SSHKeyRepository, k8s_client: K8sClient) -> None:
        self.__ssh_key_repo = ssh_key_repo
        self.__k8s_client = k8s_client

    async def authorize_session(self, public_key: str, session_id: str) -> SshSessionData:
        """Authorize a session name."""
        fingerprint = fingerprint_ssh_public_key(public_key)
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

        # temp hack for testing
        if session_id == "eike-kettner-49d93d704c1a":
            logger.info(f"Setting up remote target for {session_id} to 20.208.65.74")
            return SshSessionData(
                target_host="20.208.65.74",
                target_port=2222,
                target_user=session_id,
                host_key_pub="rc-eikek-ns1/host_key",
                auth_key_priv="rc-eikek-ns1/auth_key",
            )
        else:
            return SshSessionData(
                target_host=session_id,
                target_port=80,
                target_user="renku",
            )
