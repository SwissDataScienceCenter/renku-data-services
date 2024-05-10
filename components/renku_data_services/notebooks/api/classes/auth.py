from dataclasses import dataclass, field


@dataclass
class RenkuTokens:
    """A dataclass to hold Renku access and refresh tokens."""

    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)


@dataclass
class GitlabToken:
    """A Gitlab access token and its expiry date."""

    expires_at: int
    """Expiry date represented as Unix epoch in seconds."""
    access_token: str = field(repr=False)
