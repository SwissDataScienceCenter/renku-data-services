import json
from datetime import datetime

import pytest

from renku_data_services.data_connectors.doi.models import DOI
from renku_data_services.data_connectors.models import CloudStorageCore
from renku_data_services.data_connectors.orm import DataConnectorORM
from renku_data_services.errors import errors
from renku_data_services.namespace.orm import EntitySlugOldORM, EntitySlugORM
from renku_data_services.storage.models import RCloneConfig
from renku_data_services.storage.rclone import RCloneValidator


@pytest.mark.parametrize(
    ("raw_doi", "expected_value"),
    [
        ("doi:10.16904/12", "10.16904/12"),
        ("10.16904/12", "10.16904/12"),
        ("https://www.doi.org/10.16904/12", "10.16904/12"),
        ("http://www.doi.org/10.16904/12", "10.16904/12"),
        ("http://doi.org/10.16904/12", "10.16904/12"),
        ("http://doi.org/10.16904/12//", "10.16904/12"),
        ("http://doi.org/10.16904/12/", "10.16904/12"),
        ("http://doi.org/10.16904/12/?query=something#fragment", "10.16904/12"),
        ("http://doi.org/10.16904/12?query=something#fragment", "10.16904/12"),
        ("10.5281/zenodo.3831980", "10.5281/zenodo.3831980"),
    ],
)
def test_valid_doi_parsing(raw_doi: str, expected_value: str) -> None:
    assert DOI(raw_doi) == expected_value


@pytest.mark.parametrize(
    "raw_doi",
    [
        "wrong:10.16904/12",
        "10.1690423423432423423423/12",
        "s3://www.doi.org/10.16904/12",
        "http://test.com/10.16904/12",
        "bad",
        "really bad",
        "",
        "https:10.16904/12",
        "s3:10.16904/12",
    ],
)
def test_invalid_doi_parsing(raw_doi: str) -> None:
    with pytest.raises(errors.ValidationError):
        DOI(raw_doi)


def test_storage_configs() -> None:
    storage_from_db = DataConnectorORM(
        name="giab",
        visibility="private",
        storage_type="s3",
        configuration=json.loads('{"type": "s3", "provider": "AWS"}'),
        source_path="giab",
        target_path="external_storage/giab",
        created_by_id="d18366ec-de3a-4275-828b-c1df8e53da86",
        description=None,
        keywords=None,
        readonly=True,
        creation_date=datetime.fromisoformat("2024-10-22 11:02:10.864+0200"),
        updated_at=datetime.fromisoformat("2024-10-22 11:02:10.864+0200"),
        doi=None,
        publisher_name=None,
        publisher_url=None,
        global_slug="test",
    )
    dumped = storage_from_db.dump()
    assert isinstance(dumped.storage, CloudStorageCore)
    validator = RCloneValidator()
    validator.validate(dumped.storage.configuration)
    # How does and when CloudStorageCore get converted to RCloneConfig
    breakpoint()
