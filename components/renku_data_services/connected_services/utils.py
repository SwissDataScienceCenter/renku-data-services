"""Utilities for connected services."""

import base64
import random
from enum import StrEnum

from renku_data_services.connected_services.apispec import Provider
from renku_data_services.connected_services.apispec import ProviderKind as ApiProviderKind
from renku_data_services.connected_services.models import OAuth2Client, ProviderKind
from renku_data_services.connected_services.orm import OAuth2ClientORM
from renku_data_services.app_config import logging

logger = logging.getLogger(__name__)

def generate_code_verifier(size: int = 48) -> str:
    """Returns a randomly generated code for use in PKCE."""
    rand = random.SystemRandom()
    return base64.b64encode(rand.randbytes(size)).decode()


class GitHubProviderType(StrEnum):
    """Distinguish between the two possible authentication features at GitHub."""

    oauth_app = "oauth_app"
    standard_app = "standard_app"


def get_github_provider_type(c: OAuth2Client | OAuth2ClientORM | Provider) -> GitHubProviderType | None:
    """GitHub may use two different auth features: "oauth app" and "github app".

    Currently these two are defined as ProviderKind.github and can be
    distinguished by looking at the `image_registry_url`. If this url
    is set, it is the "oauth app" type and otherwise the standard
    "github app".
    """
    if c.kind == ProviderKind.github or c.kind == ApiProviderKind.github:
        result = GitHubProviderType.oauth_app if c.image_registry_url else GitHubProviderType.standard_app
        logger.debug(f"Using github provider type: {result} for {c.kind}/{c.image_registry_url}")
        return result
    else:
        return None
