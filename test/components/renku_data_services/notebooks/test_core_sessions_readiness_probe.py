"""Tests for readiness probe behaviour in core_sessions."""

from renku_data_services.notebooks.core_sessions import _get_readiness_probe
from renku_data_services.notebooks.crs import SessionLocation, Type
from renku_data_services.notebooks.models import SessionType


class TestGetReadinessProbe:
    """Unit tests for _get_readiness_probe helper."""

    def test_non_interactive_always_none(self) -> None:
        """Non-interactive sessions should have no readiness probe regardless of location."""
        for location in (SessionLocation.local, SessionLocation.remote):
            probe = _get_readiness_probe(SessionType.non_interactive, location)
            assert probe.type == Type.none, f"Expected none for {location}"

    def test_interactive_local_uses_tcp(self) -> None:
        """Interactive local sessions should keep the default TCP readiness probe."""
        probe = _get_readiness_probe(SessionType.interactive, SessionLocation.local)
        assert probe.type == Type.tcp

    def test_interactive_remote_uses_http(self) -> None:
        """Interactive remote sessions should use an HTTP readiness probe."""
        probe = _get_readiness_probe(SessionType.interactive, SessionLocation.remote)
        assert probe.type == Type.http
