"""Tests for ssh_proxy_session_extras in core_sessions."""

from pathlib import PurePosixPath

from renku_data_services.notebooks.config.dynamic import _SessionSshConfig
from renku_data_services.notebooks.core_sessions import ssh_proxy_session_extras


class TestSshProxySessionExtras:
    """Unit tests for the proxy-to-session volume helper."""

    def test_mounts_both_secrets(self) -> None:
        """Both secrets are mounted as subPath files under the mount dir's .ssh."""
        ssh = _SessionSshConfig(proxy_host_key_secret="host-secret", proxy_auth_key_secret="auth-secret")
        extras = ssh_proxy_session_extras(ssh, PurePosixPath("/workspace"))

        assert [v.name for v in extras.volumes] == ["ssh-session-host-key", "ssh-proxy-session-auth-key"]
        host_volume, auth_volume = extras.volumes
        assert host_volume.secret is not None
        assert host_volume.secret.secretName == "host-secret"
        assert [i.path for i in host_volume.secret.items or []] == ["dropbear_ed25519_host_key"]
        assert auth_volume.secret is not None
        assert auth_volume.secret.secretName == "auth-secret"
        assert [i.path for i in auth_volume.secret.items or []] == ["proxy_auth_key.pub"]

        mounts = {m.name: m for m in extras.volume_mounts}
        assert mounts["ssh-session-host-key"].mountPath == "/workspace/.ssh/dropbear_ed25519_host_key"
        assert mounts["ssh-session-host-key"].subPath == "dropbear_ed25519_host_key"
        assert mounts["ssh-session-host-key"].readOnly is True
        assert mounts["ssh-proxy-session-auth-key"].mountPath == "/workspace/.ssh/proxy_auth_key.pub"
        assert mounts["ssh-proxy-session-auth-key"].subPath == "proxy_auth_key.pub"
        assert mounts["ssh-proxy-session-auth-key"].readOnly is True

    def test_no_mounts_without_secret_config(self) -> None:
        """Nothing is mounted when the chart has not provided secret names."""
        extras = ssh_proxy_session_extras(_SessionSshConfig(), PurePosixPath("/workspace"))
        assert extras.volumes == []
        assert extras.volume_mounts == []
