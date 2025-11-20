import pytest

from renku_data_services.data_connectors.doi.models import DOI
from renku_data_services.errors import errors


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
