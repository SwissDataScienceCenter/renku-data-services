"""Configuration for user preferences."""

import os
from dataclasses import dataclass
from typing import Self


@dataclass(frozen=True, eq=True, kw_only=True)
class UserPreferencesConfig:
    """User preferences configuration."""

    max_pinned_projects: int

    @classmethod
    def from_env(cls) -> Self:
        """Load config from environment."""
        max_pinned_projects = int(os.environ.get("MAX_PINNED_PROJECTS", "10"))
        return cls(max_pinned_projects=max_pinned_projects)
