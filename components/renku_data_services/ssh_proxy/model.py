"""Data model for ssh proxy."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SshSessionData:
    """The data used to connect to a session via ssh."""

    target_host: str
    target_port: int
    target_user: str
    host_key_pub: str | None = None
    auth_key_priv: str | None = None

    @classmethod
    def default(cls, session_name: str) -> SshSessionData:
        """Create the default configuration for local sessions."""
        return SshSessionData(
            target_host=session_name,
            target_port=80,
            target_user="renku",
        )
