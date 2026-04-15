"""Core logic for internal authentication."""

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from renku_data_services import base_models, errors
from renku_data_services.app_config import logging
from renku_data_services.notebooks import cr_amalthea_session

if TYPE_CHECKING:
    from renku_data_services.notebooks.api.classes.k8s_client import NotebookK8sClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class ScopeVerifier:
    """Verifies the scope claim for internal authentication tokens."""

    k8s_client: "NotebookK8sClient"

    async def verify_scope(self, user: base_models.APIUser, scope: str) -> None:
        """Verify that the scope claim is valid.

        * For "session:{server_name}", check that the corresponding session is running
        """
        scopes = scope.split(" ")
        logger.info(f"Verifying scopes: {scopes}")
        await asyncio.gather(*(self._verify_scope_item(user=user, scope_item=item) for item in scopes))

    async def _verify_scope_item(self, user: base_models.APIUser, scope_item: str) -> None:
        """Verify a single scope item."""
        splits = scope_item.split(":", 1)
        match splits:
            case _ if len(splits) == 2 and splits[0].lower() == "session":
                return await self._verify_session_scope(user=user, server_name=splits[1])
            case _:
                logger.warning(f"Got unknown scope item: {scope_item}")
                return None

    async def _verify_session_scope(self, user: base_models.APIUser, server_name: str) -> None:
        """Verify a scope item corresponding to a session."""
        logger.info(f"Verifying session: {server_name}")
        if not user.is_authenticated or not user.id:
            raise errors.UnauthorizedError()

        session = await self.k8s_client.get_session(name=server_name, safe_username=user.id)
        if session is None or session.status.state.value.lower() == cr_amalthea_session.State.Hibernated.value.lower():
            raise errors.ForbiddenError(detail=f"Failed to verify session scope '{server_name}'.")
        return None
