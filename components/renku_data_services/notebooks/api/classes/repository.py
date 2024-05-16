from dataclasses import dataclass

INTERNAL_GITLAB_PROVIDER = "INTERNAL_GITLAB"


@dataclass
class Repository:
    """Information required to clone a git repository."""

    url: str
    provider: str | None = None
    dirname: str | None = None
    branch: str | None = None
    commit_sha: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, str]):
        return cls(
            url=data["url"],
            dirname=data.get("dirname"),
            branch=data.get("branch"),
            commit_sha=data.get("commit_sha"),
        )


@dataclass
class GitProvider:
    """A fully-configured git provider."""

    id: str
    url: str
    connection_id: str
    access_token_url: str


@dataclass
class OAuth2Provider:
    """An OAuth2 provider."""

    id: str
    url: str

    @classmethod
    def from_dict(cls, data: dict[str, str]):
        return cls(id=data["id"], url=data["url"])


@dataclass
class OAuth2Connection:
    """An OAuth2 connection."""

    id: str
    provider_id: str
    status: str

    @classmethod
    def from_dict(cls, data: dict[str, str]):
        return cls(id=data["id"], provider_id=data["provider_id"], status=data["status"])
