"""Tests for MCP access token verification."""

from __future__ import annotations

import datetime

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from renku_data_services.mcp_api.auth import TokenVerificationError, TokenVerifier

ISSUER = "https://renkulab.io/auth/realms/Renku"


@pytest.fixture(scope="module")
def private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def verifier(private_key, monkeypatch) -> TokenVerifier:
    """A verifier whose JWKS lookup returns the test key instead of calling Keycloak."""
    v = TokenVerifier(issuer_url=ISSUER, audience="renku-mcp")

    class _Key:
        key = private_key.public_key()

    class _JWKS:
        def get_signing_key_from_jwt(self, token):
            return _Key()

    monkeypatch.setattr(type(v), "jwks", property(lambda self: _JWKS()))
    return v


def make_token(private_key, **overrides) -> str:
    """Mint a token that passes verification unless an override breaks it."""
    now = datetime.datetime.now(datetime.UTC)
    claims = {
        "iss": ISSUER,
        "aud": ["renku", "renku-mcp"],
        "exp": now + datetime.timedelta(minutes=5),
        "iat": now,
        "sub": "user-1",
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256")


def test_accepts_token_with_both_audiences(verifier, private_key):
    """The deployed shape: one audience for this server, one for the data API."""
    claims = verifier.verify(make_token(private_key))
    assert claims["sub"] == "user-1"
    assert "renku" in claims["aud"], "the data API audience must survive, since the token is forwarded on"


def test_rejects_token_for_another_renku_client(verifier, private_key):
    """A UI or CLI token carries 'renku' but not 'renku-mcp' — this is the check's whole point."""
    with pytest.raises(TokenVerificationError, match="not issued for this server"):
        verifier.verify(make_token(private_key, aud=["renku", "renku-ui"]))


def test_rejects_expired_token(verifier, private_key):
    now = datetime.datetime.now(datetime.UTC)
    with pytest.raises(TokenVerificationError):
        verifier.verify(
            make_token(private_key, exp=now - datetime.timedelta(minutes=1), iat=now - datetime.timedelta(hours=1))
        )


def test_rejects_token_from_another_issuer(verifier, private_key):
    with pytest.raises(TokenVerificationError):
        verifier.verify(make_token(private_key, iss="https://evil.example.com/realms/Renku"))


def test_rejects_token_signed_by_another_key(verifier):
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(TokenVerificationError):
        verifier.verify(make_token(other_key))


def test_rejects_garbage(verifier):
    with pytest.raises(TokenVerificationError):
        verifier.verify("not-a-jwt")


def test_jwks_failure_rejects_rather_than_admits(private_key):
    """If the keys can't be fetched the token is refused, not waved through."""
    v = TokenVerifier(issuer_url=ISSUER)

    class _Broken:
        def get_signing_key_from_jwt(self, token):
            raise ConnectionError("keycloak unreachable")

    object.__setattr__(v, "_jwks", _Broken())
    with pytest.raises(TokenVerificationError, match="Could not verify"):
        v.verify(make_token(private_key))


def test_from_env_requires_issuer(monkeypatch):
    monkeypatch.delenv("KEYCLOAK_ISSUER_URL", raising=False)
    assert TokenVerifier.from_env() is None


def test_from_env_reads_audience_override(monkeypatch):
    monkeypatch.setenv("KEYCLOAK_ISSUER_URL", ISSUER + "/")
    monkeypatch.setenv("RENKU_MCP_AUDIENCE", "custom-aud")
    v = TokenVerifier.from_env()
    assert v is not None
    assert v.audience == "custom-aud"
    assert v.issuer_url == ISSUER, "trailing slash should be normalised away"
