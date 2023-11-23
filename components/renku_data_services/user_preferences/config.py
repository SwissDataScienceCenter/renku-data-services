"""Configuration for user preferences."""
from dataclasses import dataclass


@dataclass(frozen=True, eq=True, kw_only=True)
class UserPreferencesConfig:
    """User preferences configuration."""

    max_pinned_projects: int
