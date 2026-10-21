"""Model of a Git repository used by notebooks."""

from dataclasses import dataclass
from typing import Any, Self

INTERNAL_GITLAB_PROVIDER = "INTERNAL_GITLAB"


@dataclass
class Repository:
    """Information required to clone a git repository.

    references is the list of refs that can be pushed to:
        references == None -> no restrictions
        references == [] -> read only
        len(references) > 0 -> only listed branches are allowed

        E.g. references=["refs/heads/dev"], means only branch dev is writable
    """

    url: str
    provider: str | None = None
    dirname: str | None = None
    branch: str | None = None
    commit_sha: str | None = None
    references: list[str] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create a repository from a dictionary."""
        return cls(
            url=data["url"],
            dirname=data.get("dirname"),
            branch=data.get("branch"),
            commit_sha=data.get("commit_sha"),
            references=data.get("references"),
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
    def from_dict(cls, data: dict[str, str]) -> Self:
        """Create a provider from a dictionary."""
        return cls(id=data["id"], url=data["url"])


@dataclass
class OAuth2Connection:
    """An OAuth2 connection."""

    id: str
    provider_id: str
    status: str

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> Self:
        """Creat an OAuth2 connection from a dictonary."""
        return cls(id=data["id"], provider_id=data["provider_id"], status=data["status"])
