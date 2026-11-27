"""Tests for the outgoing HTTP proxy of sessions."""

from types import SimpleNamespace
from typing import cast

import pytest

from renku_data_services.base_models import RESET
from renku_data_services.errors import errors
from renku_data_services.notebooks.config import NotebooksConfig
from renku_data_services.notebooks.config.dynamic import _SessionProxyConfig
from renku_data_services.notebooks.core_sessions import _get_session_proxy
from renku_data_services.notebooks.crs import (
    AmaltheaSessionV1Alpha1Patch,
    AmaltheaSessionV1Alpha1SpecPatch,
    Proxy,
)

_ENV_VARS = (
    "NB_SESSIONS__PROXY__HTTP_PROXY",
    "NB_SESSIONS__PROXY__HTTPS_PROXY",
    "NB_SESSIONS__PROXY__NO_PROXY",
)


@pytest.fixture(autouse=True)
def _clear_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_proxy_config_not_set() -> None:
    assert _SessionProxyConfig.from_env() is None


def test_proxy_config_https_defaults_to_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NB_SESSIONS__PROXY__HTTP_PROXY", "http://proxy.example.ch:3128")
    monkeypatch.setenv("NB_SESSIONS__PROXY__NO_PROXY", "localhost,.svc")

    config = _SessionProxyConfig.from_env()

    assert config == _SessionProxyConfig(
        http_proxy="http://proxy.example.ch:3128",
        https_proxy="http://proxy.example.ch:3128",
        no_proxy="localhost,.svc",
    )


def test_proxy_config_all_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NB_SESSIONS__PROXY__HTTP_PROXY", "http://proxy.example.ch:3128")
    monkeypatch.setenv("NB_SESSIONS__PROXY__HTTPS_PROXY", "https://secure-proxy.example.ch:3129")

    config = _SessionProxyConfig.from_env()

    assert config is not None
    assert config.https_proxy == "https://secure-proxy.example.ch:3129"
    assert config.no_proxy == ""


@pytest.mark.parametrize(
    "env",
    [
        {"NB_SESSIONS__PROXY__HTTP_PROXY": "proxy.example.ch:3128"},
        {
            "NB_SESSIONS__PROXY__HTTP_PROXY": "http://proxy.example.ch:3128",
            "NB_SESSIONS__PROXY__HTTPS_PROXY": "socks5://proxy.example.ch:1080",
        },
        {"NB_SESSIONS__PROXY__NO_PROXY": "localhost"},
    ],
)
def test_proxy_config_invalid(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(errors.ConfigurationError):
        _SessionProxyConfig.from_env()


def _nb_config(proxy: _SessionProxyConfig | None) -> NotebooksConfig:
    return cast(NotebooksConfig, SimpleNamespace(sessions=SimpleNamespace(proxy=proxy)))


def test_get_session_proxy() -> None:
    assert _get_session_proxy(_nb_config(None)) is None

    proxy = _get_session_proxy(
        _nb_config(_SessionProxyConfig(http_proxy="http://proxy:3128", https_proxy="http://proxy:3128"))
    )

    # All fields are set so that a merge patch overwrites values from a previous configuration
    assert proxy == Proxy(httpProxy="http://proxy:3128", httpsProxy="http://proxy:3128", noProxy="")


def test_session_patch_proxy() -> None:
    patch = AmaltheaSessionV1Alpha1Patch(
        spec=AmaltheaSessionV1Alpha1SpecPatch(
            proxy=Proxy(httpProxy="http://proxy:3128", httpsProxy="http://proxy:3128", noProxy="")
        )
    )
    assert patch.to_rfc7386() == {
        "spec": {"proxy": {"httpProxy": "http://proxy:3128", "httpsProxy": "http://proxy:3128", "noProxy": ""}}
    }

    patch = AmaltheaSessionV1Alpha1Patch(spec=AmaltheaSessionV1Alpha1SpecPatch(proxy=RESET))
    assert patch.to_rfc7386() == {"spec": {"proxy": None}}
