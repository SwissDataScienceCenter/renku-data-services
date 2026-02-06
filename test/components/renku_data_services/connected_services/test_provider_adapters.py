"""Tests for provider adapters."""

from datetime import UTC, datetime

import pytest
from ulid import ULID

from renku_data_services.connected_services import models
from renku_data_services.connected_services import orm as schemas
from renku_data_services.connected_services.provider_adapters import get_provider_adapter


@pytest.mark.parametrize("provider_kind", list(models.ProviderKind))
def test_get_provider_adapter_maps_all_providers(provider_kind: models.ProviderKind) -> None:
    client = schemas.OAuth2ClientORM(
        id=ULID(),
        client_id=f"c-{provider_kind.value}",
        display_name=provider_kind.value,
        created_by_id="",
        kind=provider_kind,
        scope="",
        url="https://dev.renku.ch",
        use_pkce=False,
        app_slug="",
        client_secret=None,
        creation_date=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        image_registry_url=None,
        oidc_issuer_url=None,
    )

    adapter = get_provider_adapter(client)

    assert adapter is not None
