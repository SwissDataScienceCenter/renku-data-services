from dataclasses import dataclass, field


@dataclass
class RenkuTokens:
    """A dataclass to hold Renku access and refresh tokens."""

    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)


@dataclass
class GitlabToken:
    """A dataclass that hold a Gitlab access token and its expiry date
    represented as Unix epoch in seconds."""

    expires_at: int
    access_token: str = field(repr=False)
