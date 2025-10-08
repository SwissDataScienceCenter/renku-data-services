import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import pytest
from httpx import Response
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.authz.models import Visibility
from renku_data_services.base_models.core import NamespacePath, ProjectPath
from renku_data_services.data_connectors import core
from renku_data_services.data_connectors.doi.models import DOIMetadata
from renku_data_services.namespace.models import NamespaceKind
from renku_data_services.storage.rclone import RCloneDOIMetadata
from renku_data_services.users.models import UserInfo
from renku_data_services.utils.core import get_openbis_session_token
from test.bases.renku_data_services.data_api.utils import merge_headers

if TYPE_CHECKING:
    from pytest import MonkeyPatch


async def create_data_connector(
    sanic_client: SanicASGITestClient, headers: dict[str, Any], namespace: str, slug: str, private: bool
) -> Response:
    storage_config = {
        "configuration": {"type": "s3", "endpoint": "http://s3.aws.com"},
        "source_path": "giab",
        "target_path": "giab",
    }
    payload = {
        "name": slug,
        "namespace": namespace,
        "slug": slug,
        "storage": storage_config,
        "visibility": "private" if private else "public",
    }
    _, response = await sanic_client.post("/api/data/data_connectors", headers=headers, json=payload)
    return cast(Response, response)


@pytest.mark.asyncio
async def test_post_data_connector(
    sanic_client: SanicASGITestClient, regular_user: UserInfo, user_headers, app_manager
) -> None:
    payload = {
        "name": "My data connector",
        "slug": "my-data-connector",
        "description": "A data connector",
        "visibility": "public",
        "namespace": regular_user.namespace.path.serialize(),
        "storage": {
            "configuration": {
                "type": "s3",
                "provider": "AWS",
                "region": "us-east-1",
            },
            "source_path": "bucket/my-folder",
            "target_path": "my/target",
        },
        "keywords": ["keyword 1", "keyword.2", "keyword-3", "KEYWORD_4"],
    }

    _, response = await sanic_client.post("/api/data/data_connectors", headers=user_headers, json=payload)

    assert response.status_code == 201, response.text
    assert response.json is not None
    data_connector = response.json
    assert data_connector.get("name") == "My data connector"
    assert data_connector.get("namespace") == "user.doe"
    assert data_connector.get("slug") == "my-data-connector"
    assert data_connector.get("storage") is not None
    storage = data_connector["storage"]
    assert storage.get("storage_type") == "s3"
    assert storage.get("source_path") == "bucket/my-folder"
    assert storage.get("target_path") == "my/target"
    assert storage.get("readonly") is True
    assert data_connector.get("created_by") == "user"
    assert data_connector.get("visibility") == "public"
    assert data_connector.get("description") == "A data connector"
    assert set(data_connector.get("keywords")) == {"keyword 1", "keyword.2", "keyword-3", "KEYWORD_4"}
    app_manager.metrics.data_connector_created.assert_called_once()

    # Check that we can retrieve the data connector
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector['id']}", headers=user_headers)
    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json.get("id") == data_connector["id"]

    # Check that we can retrieve the data connector by slug
    _, response = await sanic_client.get(
        f"/api/data/namespaces/{data_connector['namespace']}/data_connectors/{data_connector['slug']}",
        headers=user_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json.get("id") == data_connector["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "doi", ["10.5281/zenodo.2600782", "doi:10.5281/zenodo.2600782", "https://doi.org/10.5281/zenodo.2600782"]
)
async def test_post_global_data_connector(
    sanic_client: SanicASGITestClient, user_headers: dict[str, str], monkeypatch: "MonkeyPatch", doi: str
) -> None:
    # The DOI resolver seems to block requests from GitHub action runners, so we mock its response
    metadata = RCloneDOIMetadata(
        DOI="10.5281/zenodo.2600782",
        URL="https://doi.org/10.5281/zenodo.2600782",
        metadataURL="https://zenodo.org/api/records/3542869",
        provider="zenodo",
    )
    _mock_get_doi_metadata(metadata=metadata, sanic_client=sanic_client, monkeypatch=monkeypatch)
    zenodo_metadata = DOIMetadata(
        name="SwissDataScienceCenter/renku-python: Version 0.7.2",
        description="""<a href="https://github.com/SwissDataScienceCenter/renku-python/compare/v0.7.1...v0.7.2">0.7.2</a> (2019-11-15)\nBug Fixes\n<ul>\n<li>ensure all Person instances have valid ids (<a href="https://github.com/SwissDataScienceCenter/renku-python/commit/85585d0">85585d0</a>), addresses <a href="https://github.com/SwissDataScienceCenter/renku-python/issues/812">#812</a></li>\n</ul>""",  # noqa E501
        keywords=[],
    )
    _mock_get_dataset_metadata(metadata=zenodo_metadata, sanic_client=sanic_client, monkeypatch=monkeypatch)

    payload = {
        "storage": {
            "configuration": {"type": "doi", "doi": doi},
            "source_path": "",
            "target_path": "",
        },
    }

    _, response = await sanic_client.post("/api/data/data_connectors/global", headers=user_headers, json=payload)

    assert response.status_code == 201, response.text
    assert response.json is not None
    data_connector = response.json
    assert data_connector.get("name") == "SwissDataScienceCenter/renku-python: Version 0.7.2"
    assert data_connector.get("slug") == "doi-10.5281-zenodo.2600782"
    assert data_connector.get("storage") is not None
    storage = data_connector["storage"]
    assert storage.get("storage_type") == "doi"
    assert storage.get("source_path") == "/"
    assert storage.get("target_path") == "swissdatasciencecenter-renku-p-doi-10.5281-zenodo.2600782"
    assert storage.get("readonly") is True
    assert data_connector.get("visibility") == "public"
    assert data_connector.get("description") is not None
    assert set(data_connector.get("keywords")) == set()

    # Check that we can retrieve the data connector
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector['id']}", headers=user_headers)
    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json.get("id") == data_connector["id"]

    # Check that we can retrieve the data connector by slug
    _, response = await sanic_client.get(
        f"/api/data/data_connectors/global/{data_connector['slug']}",
        headers=user_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json.get("id") == data_connector["id"]


@pytest.mark.asyncio
async def test_post_global_data_connector_dataverse(
    sanic_client: SanicASGITestClient, user_headers: dict[str, str], monkeypatch: "MonkeyPatch"
) -> None:
    # The DOI resolver seems to block requests from GitHub action runners, so we mock its response
    metadata = RCloneDOIMetadata(
        DOI="10.7910/DVN/2SA6SN",
        URL="https://doi.org/10.7910/DVN/2SA6SN",
        metadataURL="https://dataverse.harvard.edu/api/datasets/:persistentId/?persistentId=doi%3A10.7910%2FDVN%2F2SA6SN",
        provider="dataverse",
    )
    _mock_get_doi_metadata(metadata=metadata, sanic_client=sanic_client, monkeypatch=monkeypatch)
    dataverse_metadata = DOIMetadata(
        name="Dataset metadata of known Dataverse installations, August 2024",
        description="""<p>This dataset contains the metadata of the datasets published in 101 Dataverse installations, information about the metadata blocks of 106 installations, and the lists of pre-defined licenses or dataset terms that depositors can apply to datasets in the 88 installations that were running versions of the Dataverse software that include the "multiple-license" feature.\n\n<p>The data is useful for improving understandings about how certain Dataverse features and metadata fields are used and for learning about the quality of dataset and file-level metadata within and across Dataverse installations.\n\n<p><strong>How the metadata was downloaded</strong>\n<p>The dataset metadata and metadata block JSON files were downloaded from each installation between August 25 and August 30, 2024 using a "get_dataverse_installations_metadata" function in a collection of Python functions at <a href="https://github.com/jggautier/dataverse-scripts/blob/main/dataverse_repository_curation_assistant/dataverse_repository_curation_assistant_functions.py">https://github.com/jggautier/dataverse-scripts/blob/main/dataverse_repository_curation_assistant/dataverse_repository_curation_assistant_functions.py</a>.\n\n<p>In order to get the metadata from installations that require an installation account API token to use certain Dataverse software APIs, I created a CSV file with two columns: one column named "hostname" listing each installation URL for which I was able to create an account and another column named "apikey" listing my accounts\' API tokens. The Python script expects the CSV file and the listed API tokens to get metadata and other information from installations that require API tokens in order to use certain API endpoints.\n\n<p><strong>How the files are organized</strong>\n\n<pre>\n├── csv_files_with_metadata_from_most_known_dataverse_installations\n│\xa0\xa0 ├── author_2024.08.25-2024.08.30.csv\n│\xa0\xa0 ├── contributor_2024.08.25-2024.08.30.csv\n│\xa0\xa0 ├── data_source_2024.08.25-2024.08.30.csv\n│\xa0\xa0 ├── ...\n│\xa0\xa0 └── topic_classification_2024.08.25-2024.08.30.csv\n├── dataverse_json_metadata_from_each_known_dataverse_installation\n│\xa0\xa0 ├── Abacus_2024.08.26_15.52.42.zip\n│\xa0\xa0\xa0\xa0\xa0\xa0 ├── dataset_pids_Abacus_2024.08.26_15.52.42.csv\n│\xa0\xa0\xa0\xa0\xa0\xa0 ├── Dataverse_JSON_metadata_2024.08.26_15.52.42\n│\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0  ├── hdl_11272.1_AB2_0AQZNT_v1.0(latest_version).json\n│\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0  ├── ...\n│\xa0\xa0\xa0\xa0\xa0\xa0 ├── metadatablocks_v5.9\n│\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0  ├── astrophysics_v5.9.json\n│\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0  ├── biomedical_v5.9.json\n│\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0  ├── citation_v5.9.json\n│\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0  ├── ...\n│\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0  ├── socialscience_v5.6.json\n│\xa0\xa0 ├── ACSS_Dataverse_2024.08.26_00.02.51.zip\n│\xa0\xa0 ├── ...\n│\xa0\xa0 └── Yale_Dataverse_2024.08.25_03.52.57.zip\n└── dataverse_installations_summary_2024.08.30.csv\n└── dataset_pids_from_most_known_dataverse_installations_2024.08.csv\n└── license_options_for_each_dataverse_installation_2024.08.28_14.42.54.csv\n└── metadatablocks_from_most_known_dataverse_installations_2024.08.30.csv\n\n</pre>\n\n<p>This dataset contains two directories and four CSV files not in a directory.\n<p>One directory, "csv_files_with_metadata_from_most_known_dataverse_installations", contains 20 CSV files that list the values of many of the metadata fields in the "Citation" metadata block and "Geospatial" metadata block of datasets in the 101 Dataverse installations. For example, author_2024.08.25-2024.08.30.csv contains the "Author" metadata for the latest versions of all published, non-deaccessioned datasets in 101 installations, with a column for each of the four child fields: author name, affiliation, identifier type, and identifier.\n<p>The other directory, "dataverse_json_metadata_from_each_known_dataverse_installation", contains 106 zip files, one zip file for each of the 106 Dataverse installations whose sites were functioning when I attempted to collect their metadata. Each zip file contains a directory with JSON files that have information about the installation\'s metadata fields, such as the field names and how they\'re organized. For installations that had published datasets, and I was able to use Dataverse APIs to download the dataset metadata, the zip file also contains:\n<ul>\n<li>A CSV file listing information about the datasets published in the installation, including a column to indicate if the Python script was able to download the Dataverse JSON metadata for each dataset.\n<li>A directory of JSON files that contain the metadata of the installation\'s published, non-deaccessioned dataset versions in the Dataverse JSON metadata schema.\n</ul>\n<p>The dataverse_installations_summary_2024.08.30.csv file contains information about each installation, including its name, URL, Dataverse software version, and counts of dataset metadata included and not included in this dataset.\n<p>The dataset_pids_from_most_known_dataverse_installations_2024.08.csv file contains the dataset PIDs of published datasets in 101 Dataverse installations, with a column to indicate if the Python script was able to download the dataset\'s metadata. It\'s a union of all "dataset_pids_....csv" files in each of the 101 zip files in the dataverse_json_metadata_from_each_known_dataverse_installation directory.\n<p>The license_options_for_each_dataverse_installation_2024.08.28_14.42.54.csv file contains information about the licenses and data use agreements that some installations let depositors choose when creating datasets. When I collected this data, 88 of the available 106 installations were running versions of the Dataverse software that allow depositors to choose a "predefined license or data use agreement" from a dropdown menu in the dataset deposit form. For more information about this Dataverse feature, see <a href="https://guides.dataverse.org/en/5.14/user/dataset-management.html#choosing-a-license">https://guides.dataverse.org/en/5.14/user/dataset-management.html#choosing-a-license</a>.\n<p>The metadatablocks_from_most_known_dataverse_installations_2024.08.30.csv file contains the metadata block names, field names, child field names (if the field is a compound field), display names, descriptions/tooltip text, and watermarks of fields in the 106 Dataverse installations\' metadata blocks. This file is useful for learning about the metadata fields and field structures used in each installation.\n\n<p><strong>Known errors</strong>\n<p>The metadata of a few datasets from several known and functioning installations could not be downloaded.\n<p>In some cases, this is because of download timeouts caused by the datasets\' relatively large metadata exports, which contain information about the datasets\' large number of versions and files.\n<p>In other cases, datasets were publicly findable but in unpublished or deaccessioned states that prevented me from downloading their metadata export.\n\n<p><strong>About metadata blocks</strong>\n<p>Read about the Dataverse software\'s metadata blocks system at <a href="http://guides.dataverse.org/en/latest/admin/metadatacustomization.html">http://guides.dataverse.org/en/6.3/admin/metadatacustomization.html</a>""",  # noqa E501
        keywords=["dataset metadata", "dataverse", "metadata blocks"],
    )
    _mock_get_dataset_metadata(metadata=dataverse_metadata, sanic_client=sanic_client, monkeypatch=monkeypatch)

    doi = "10.7910/DVN/2SA6SN"
    payload = {
        "storage": {
            "configuration": {"type": "doi", "doi": doi},
            "source_path": "",
            "target_path": "",
        },
    }

    _, response = await sanic_client.post("/api/data/data_connectors/global", headers=user_headers, json=payload)

    assert response.status_code == 201, response.text
    assert response.json is not None
    data_connector = response.json
    assert data_connector.get("name") == "Dataset metadata of known Dataverse installations, August 2024"
    assert data_connector.get("slug") == "doi-10.7910-dvn-2sa6sn"
    assert data_connector.get("storage") is not None
    storage = data_connector["storage"]
    assert storage.get("storage_type") == "doi"
    assert storage.get("source_path") == "/"
    assert storage.get("target_path") == "dataset-metadata-of-known-data-doi-10.7910-dvn-2sa6sn"
    assert storage.get("readonly") is True
    assert data_connector.get("visibility") == "public"
    assert data_connector.get("description") is not None
    assert set(data_connector.get("keywords")) == {"dataset metadata", "dataverse", "metadata blocks"}


@pytest.mark.asyncio
async def test_post_global_data_connector_unauthorized(
    sanic_client: SanicASGITestClient,
) -> None:
    payload = {
        "storage": {
            "configuration": {"type": "doi", "doi": "10.5281/zenodo.15174623"},
            "source_path": "",
            "target_path": "",
        },
    }

    _, response = await sanic_client.post("/api/data/data_connectors/global", json=payload)

    assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_post_global_data_connector_invalid_doi(
    sanic_client: SanicASGITestClient,
    user_headers,
) -> None:
    payload = {
        "storage": {
            "configuration": {"type": "doi", "doi": "foo/bar"},
            "source_path": "",
            "target_path": "",
        },
    }

    _, response = await sanic_client.post("/api/data/data_connectors/global", headers=user_headers, json=payload)

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_post_global_data_connector_no_duplicates(
    sanic_client: SanicASGITestClient, user_headers: dict[str, str], monkeypatch: "MonkeyPatch"
) -> None:
    # The DOI resolver seems to block requests from GitHub action runners, so we mock its response
    metadata = RCloneDOIMetadata(
        DOI="10.5281/zenodo.2600782",
        URL="https://doi.org/10.5281/zenodo.2600782",
        metadataURL="https://zenodo.org/api/records/3542869",
        provider="zenodo",
    )
    _mock_get_doi_metadata(metadata=metadata, sanic_client=sanic_client, monkeypatch=monkeypatch)
    zenodo_metadata = DOIMetadata(
        name="SwissDataScienceCenter/renku-python: Version 0.7.2",
        description="""<a href="https://github.com/SwissDataScienceCenter/renku-python/compare/v0.7.1...v0.7.2">0.7.2</a> (2019-11-15)\nBug Fixes\n<ul>\n<li>ensure all Person instances have valid ids (<a href="https://github.com/SwissDataScienceCenter/renku-python/commit/85585d0">85585d0</a>), addresses <a href="https://github.com/SwissDataScienceCenter/renku-python/issues/812">#812</a></li>\n</ul>""",  # noqa E501
        keywords=[],
    )
    _mock_get_dataset_metadata(metadata=zenodo_metadata, sanic_client=sanic_client, monkeypatch=monkeypatch)

    doi = "10.5281/zenodo.2600782"
    payload = {
        "storage": {
            "configuration": {"type": "doi", "doi": doi},
            "source_path": "",
            "target_path": "",
        },
    }

    _, response = await sanic_client.post("/api/data/data_connectors/global", headers=user_headers, json=payload)

    assert response.status_code == 201, response.text
    assert response.json is not None
    data_connector = response.json
    data_connector_id = data_connector["id"]
    assert data_connector.get("name") == "SwissDataScienceCenter/renku-python: Version 0.7.2"
    assert data_connector.get("slug") == "doi-10.5281-zenodo.2600782"

    # Check that posting the same DOI returns the same data connector ULID
    doi = "https://doi.org/10.5281/zenodo.2600782"
    payload = {
        "storage": {
            "configuration": {"type": "doi", "doi": doi},
            "source_path": "",
            "target_path": "",
        },
    }

    _, response = await sanic_client.post("/api/data/data_connectors/global", headers=user_headers, json=payload)

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json.get("id") == data_connector_id


@pytest.mark.asyncio
async def test_post_data_connector_with_s3_url(
    sanic_client: SanicASGITestClient, regular_user: UserInfo, user_headers
) -> None:
    payload = {
        "name": "My data connector",
        "slug": "my-data-connector",
        "description": "A data connector",
        "visibility": "public",
        "namespace": regular_user.namespace.path.serialize(),
        "storage": {
            "storage_url": "s3://my-bucket",
            "target_path": "my/target",
        },
        "keywords": ["keyword 1", "keyword.2", "keyword-3", "KEYWORD_4"],
    }

    _, response = await sanic_client.post("/api/data/data_connectors", headers=user_headers, json=payload)

    assert response.status_code == 201, response.text
    assert response.json is not None
    data_connector = response.json
    assert data_connector.get("name") == "My data connector"
    assert data_connector.get("namespace") == "user.doe"
    assert data_connector.get("slug") == "my-data-connector"
    assert data_connector.get("storage") is not None
    storage = data_connector["storage"]
    assert storage.get("storage_type") == "s3"
    assert storage.get("source_path") == "my-bucket"
    assert storage.get("target_path") == "my/target"
    assert storage.get("readonly") is True
    assert data_connector.get("created_by") == "user"
    assert data_connector.get("visibility") == "public"
    assert data_connector.get("description") == "A data connector"
    assert set(data_connector.get("keywords")) == {"keyword 1", "keyword.2", "keyword-3", "KEYWORD_4"}


@pytest.mark.asyncio
async def test_post_data_connector_with_azure_url(
    sanic_client: SanicASGITestClient, regular_user: UserInfo, user_headers
) -> None:
    payload = {
        "name": "My data connector",
        "slug": "my-data-connector",
        "description": "A data connector",
        "visibility": "public",
        "namespace": regular_user.namespace.path.serialize(),
        "storage": {
            "storage_url": "azure://mycontainer/myfolder",
            "target_path": "my/target",
        },
        "keywords": ["keyword 1", "keyword.2", "keyword-3", "KEYWORD_4"],
    }

    _, response = await sanic_client.post("/api/data/data_connectors", headers=user_headers, json=payload)

    assert response.status_code == 201, response.text
    assert response.json is not None
    data_connector = response.json
    assert data_connector.get("name") == "My data connector"
    assert data_connector.get("namespace") == "user.doe"
    assert data_connector.get("slug") == "my-data-connector"
    assert data_connector.get("storage") is not None
    storage = data_connector["storage"]
    assert storage.get("storage_type") == "azureblob"
    assert storage.get("source_path") == "mycontainer/myfolder"
    assert storage.get("target_path") == "my/target"
    assert storage.get("readonly") is True
    assert data_connector.get("created_by") == "user"
    assert data_connector.get("visibility") == "public"
    assert data_connector.get("description") == "A data connector"
    assert set(data_connector.get("keywords")) == {"keyword 1", "keyword.2", "keyword-3", "KEYWORD_4"}


@pytest.mark.asyncio
async def test_post_data_connector_with_invalid_visibility(sanic_client: SanicASGITestClient, user_headers) -> None:
    payload = {"visibility": "random"}

    _, response = await sanic_client.post("/api/data/data_connectors", headers=user_headers, json=payload)

    assert response.status_code == 422, response.text
    assert "visibility: Input should be 'private' or 'public'" in response.json["error"]["message"]


@pytest.mark.asyncio
async def test_post_data_connector_with_invalid_keywords(sanic_client: SanicASGITestClient, user_headers) -> None:
    keyword = "this keyword is way too long........................................................................"
    payload = {"keywords": [keyword]}

    _, response = await sanic_client.post("/api/data/data_connectors", headers=user_headers, json=payload)

    assert response.status_code == 422, response.text
    assert "String should have at most 99 characters" in response.json["error"]["message"]


@pytest.mark.asyncio
async def test_post_data_connector_with_invalid_namespace(
    sanic_client: SanicASGITestClient,
    user_headers,
    member_1_user: UserInfo,
) -> None:
    namespace = member_1_user.namespace.path.serialize()
    _, response = await sanic_client.get(f"/api/data/namespaces/{namespace}", headers=user_headers)
    assert response.status_code == 200, response.text

    payload = {
        "name": "My data connector",
        "namespace": namespace,
        "storage": {
            "configuration": {
                "type": "s3",
                "provider": "AWS",
                "region": "us-east-1",
            },
            "source_path": "bucket/my-folder",
            "target_path": "my/target",
        },
    }
    _, response = await sanic_client.post("/api/data/data_connectors", headers=user_headers, json=payload)

    assert response.status_code == 403, response.text
    assert "you do not have sufficient permissions" in response.json["error"]["message"]


@pytest.mark.asyncio
async def test_post_data_connector_with_conflicting_slug(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers
) -> None:
    data_connector_1 = await create_data_connector("Data connector 1")

    payload = {
        "name": "My data connector",
        "namespace": data_connector_1["namespace"],
        "slug": data_connector_1["slug"],
        "storage": {
            "configuration": {
                "type": "s3",
                "provider": "AWS",
            },
            "source_path": "bucket/my-folder",
            "target_path": "my/target",
        },
    }
    _, response = await sanic_client.post("/api/data/data_connectors", headers=user_headers, json=payload)

    assert response.status_code == 409, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("headers_and_error", [("unauthorized_headers", 401), ("member_1_headers", 403)])
async def test_post_data_connector_without_namespace_permission(
    # NOTE: dynamically requesting async fixtures with an already running event loop causes errors in pytest.
    # to prevent this, all used fixtures have to also be listed again, so they exist at test execution time and
    # are loaded from cache
    sanic_client: SanicASGITestClient,
    user_headers,
    headers_and_error,
    unauthorized_headers,
    member_1_headers,
    request,
) -> None:
    headers_name, status_code = headers_and_error

    _, response = await sanic_client.post(
        "/api/data/groups", headers=user_headers, json={"name": "My Group", "slug": "my-group"}
    )
    assert response.status_code == 201, response.text

    headers = request.getfixturevalue(headers_name)
    payload = {
        "name": "My data connector",
        "namespace": "my-group",
        "storage": {
            "configuration": {
                "type": "s3",
                "provider": "AWS",
            },
            "source_path": "bucket/my-folder",
            "target_path": "my/target",
        },
    }
    _, response = await sanic_client.post("/api/data/data_connectors", headers=headers, json=payload)

    assert response.status_code == status_code, response.text


@pytest.mark.asyncio
async def test_post_data_connector_with_namespace_permission(
    sanic_client: SanicASGITestClient, user_headers, member_1_headers, member_1_user
) -> None:
    _, response = await sanic_client.post(
        "/api/data/groups", headers=user_headers, json={"name": "My Group", "slug": "my-group"}
    )
    assert response.status_code == 201, response.text
    patch = [{"id": member_1_user.id, "role": "editor"}]
    _, response = await sanic_client.patch("/api/data/groups/my-group/members", headers=user_headers, json=patch)
    assert response.status_code == 200

    payload = {
        "name": "My data connector",
        "namespace": "my-group",
        "storage": {
            "configuration": {
                "type": "s3",
                "provider": "AWS",
            },
            "source_path": "bucket/my-folder",
            "target_path": "my/target",
        },
    }
    _, response = await sanic_client.post("/api/data/data_connectors", headers=member_1_headers, json=payload)

    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_get_all_data_connectors_pagination(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers
) -> None:
    for i in range(1, 10):
        await create_data_connector(f"Data connector {i}")

    parameters = {"page": 2, "per_page": 3}
    _, response = await sanic_client.get("/api/data/data_connectors", headers=user_headers, params=parameters)

    assert response.status_code == 200, response.text
    assert response.json is not None
    data_connectors = response.json
    assert {dc["name"] for dc in data_connectors} == {
        "Data connector 4",
        "Data connector 5",
        "Data connector 6",
    }
    assert response.headers["page"] == "2"
    assert response.headers["per-page"] == "3"
    assert response.headers["total"] == "9"
    assert response.headers["total-pages"] == "3"


@pytest.mark.asyncio
async def test_get_one_data_connector(sanic_client: SanicASGITestClient, create_data_connector, user_headers) -> None:
    data_connector = await create_data_connector("A new data connector")
    data_connector_id = data_connector["id"]

    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    data_connector = response.json
    assert data_connector.get("id") == data_connector_id
    assert data_connector.get("name") == "A new data connector"
    assert data_connector.get("namespace") == "user.doe"
    assert data_connector.get("slug") == "a-new-data-connector"


@pytest.mark.asyncio
async def test_head_one_data_connector(sanic_client: SanicASGITestClient, create_data_connector, user_headers) -> None:
    data_connector = await create_data_connector("A new data connector")
    data_connector_id = data_connector["id"]

    _, response = await sanic_client.head(f"/api/data/data_connectors/{data_connector_id}", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is None


@pytest.mark.asyncio
async def test_get_one_by_slug_data_connector(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers
) -> None:
    data_connector = await create_data_connector("A new data connector")
    namespace = data_connector["namespace"]
    slug = data_connector["slug"]

    _, response = await sanic_client.get(
        f"/api/data/namespaces/{namespace}/data_connectors/{slug}", headers=user_headers
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    data_connector = response.json
    assert data_connector.get("id") == data_connector["id"]
    assert data_connector.get("name") == "A new data connector"
    assert data_connector.get("namespace") == "user.doe"
    assert data_connector.get("slug") == "a-new-data-connector"


@pytest.mark.asyncio
@pytest.mark.parametrize("headers_name", ["unauthorized_headers", "member_1_headers"])
async def test_get_one_data_connector_unauthorized(
    # NOTE: dynamically requesting async fixtures with an already running event loop causes errors in pytest.
    # to prevent this, all used fixtures have to also be listed again, so they exist at test execution time and
    # are loaded from cache
    sanic_client: SanicASGITestClient,
    create_data_connector,
    headers_name,
    unauthorized_headers,
    member_1_headers,
    request,
) -> None:
    data_connector = await create_data_connector("A new data connector")
    data_connector_id = data_connector["id"]

    headers = request.getfixturevalue(headers_name)
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}", headers=headers)

    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_patch_data_connector(sanic_client: SanicASGITestClient, create_data_connector, user_headers) -> None:
    data_connector = await create_data_connector("My data connector")

    headers = merge_headers(user_headers, {"If-Match": data_connector["etag"]})
    patch = {
        "name": "New Name",
        "description": "Updated data connector",
        "keywords": ["keyword 1", "keyword 2"],
        "visibility": "public",
        "storage": {
            "configuration": {"type": "azureblob"},
            "source_path": "new/src",
            "target_path": "new/target",
            "readonly": False,
        },
    }
    data_connector_id = data_connector["id"]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}", headers=headers, json=patch
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    data_connector = response.json
    assert data_connector.get("name") == "New Name"
    assert data_connector.get("namespace") == "user.doe"
    assert data_connector.get("slug") == "my-data-connector"
    assert data_connector.get("storage") is not None
    storage = data_connector["storage"]
    assert storage.get("storage_type") == "azureblob"
    assert storage.get("source_path") == "new/src"
    assert storage.get("target_path") == "new/target"
    assert storage.get("readonly") is False
    assert data_connector.get("created_by") == "user"
    assert data_connector.get("visibility") == "public"
    assert data_connector.get("description") == "Updated data connector"
    assert set(data_connector.get("keywords")) == {"keyword 1", "keyword 2"}


@pytest.mark.asyncio
async def test_patch_data_connector_can_unset_storage_field(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers
) -> None:
    initial_storage = {
        "configuration": {
            "provider": "AWS",
            "type": "s3",
            "region": "us-east-1",
            "access_key_id": "ACCESS KEY",
            "secret_access_key": "SECRET",
        },
        "source_path": "my-bucket",
        "target_path": "my_data",
    }
    data_connector = await create_data_connector("My data connector", storage=initial_storage)

    headers = merge_headers(user_headers, {"If-Match": data_connector["etag"]})
    data_connector_id = data_connector["id"]
    patch = {"storage": {"configuration": {"region": None, "access_key_id": None, "secret_access_key": None}}}
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}", headers=headers, json=patch
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    new_configuration = response.json["storage"]["configuration"]
    assert new_configuration is not None
    assert new_configuration["provider"] == "AWS"
    assert new_configuration["type"] == "s3"
    assert "region" not in new_configuration
    assert "access_key_id" not in new_configuration
    assert "secret_access_key" not in new_configuration
    assert len(response.json["storage"]["sensitive_fields"]) == 0


@pytest.mark.asyncio
async def test_patch_data_connector_visibility_to_private_hides_data_connector(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers
) -> None:
    data_connector = await create_data_connector("My data connector", visibility="public")

    _, response = await sanic_client.get("/api/data/data_connectors")
    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json[0]["name"] == "My data connector"

    headers = merge_headers(user_headers, {"If-Match": data_connector["etag"]})
    patch = {
        "visibility": "private",
    }
    data_connector_id = data_connector["id"]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}", headers=headers, json=patch
    )
    assert response.status_code == 200, response.text

    _, response = await sanic_client.get("/api/data/data_connectors")

    assert len(response.json) == 0


@pytest.mark.asyncio
async def test_patch_data_connector_visibility_to_public_shows_data_connector(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers
) -> None:
    data_connector = await create_data_connector("My data connector", visibility="private")

    _, response = await sanic_client.get("/api/data/data_connectors")
    assert response.status_code == 200, response.text
    assert response.json is not None
    assert len(response.json) == 0

    headers = merge_headers(user_headers, {"If-Match": data_connector["etag"]})
    patch = {
        "visibility": "public",
    }
    data_connector_id = data_connector["id"]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}", headers=headers, json=patch
    )
    assert response.status_code == 200, response.text

    _, response = await sanic_client.get("/api/data/data_connectors")

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json[0]["name"] == "My data connector"


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["id", "created_by", "creation_date"])
async def test_patch_data_connector_reserved_fields_are_forbidden(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers, field
) -> None:
    data_connector = await create_data_connector("My data connector")
    original_value = data_connector[field]

    headers = merge_headers(user_headers, {"If-Match": data_connector["etag"]})
    patch = {
        field: "new-value",
    }
    data_connector_id = data_connector["id"]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}", headers=headers, json=patch
    )

    assert response.status_code == 422, response.text
    assert f"{field}: Extra inputs are not permitted" in response.text

    # Check that the field's value didn't change
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}", headers=user_headers)
    assert response.status_code == 200, response.text
    data_connector = response.json
    assert data_connector[field] == original_value


@pytest.mark.asyncio
async def test_patch_data_connector_without_if_match_header(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers
) -> None:
    data_connector = await create_data_connector("My data connector")
    original_value = data_connector["name"]

    patch = {
        "name": "New Name",
    }
    data_connector_id = data_connector["id"]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}", headers=user_headers, json=patch
    )

    assert response.status_code == 428, response.text
    assert "If-Match header not provided" in response.text

    # Check that the field's value didn't change
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}", headers=user_headers)
    assert response.status_code == 200, response.text
    data_connector = response.json
    assert data_connector["name"] == original_value


@pytest.mark.asyncio
async def test_patch_data_connector_namespace(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers
) -> None:
    _, response = await sanic_client.post(
        "/api/data/groups", headers=user_headers, json={"name": "My Group", "slug": "my-group"}
    )
    assert response.status_code == 201, response.text
    data_connector = await create_data_connector("My data connector")

    headers = merge_headers(user_headers, {"If-Match": data_connector["etag"]})
    patch = {"namespace": "my-group"}
    data_connector_id = data_connector["id"]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}", headers=headers, json=patch
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    data_connector = response.json
    assert data_connector.get("id") == data_connector_id
    assert data_connector.get("name") == "My data connector"
    assert data_connector.get("namespace") == "my-group"
    assert data_connector.get("slug") == "my-data-connector"

    # Check that we can retrieve the data connector by slug
    _, response = await sanic_client.get(
        f"/api/data/namespaces/{data_connector['namespace']}/data_connectors/{data_connector['slug']}",
        headers=user_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json.get("id") == data_connector["id"]


@pytest.mark.asyncio
async def test_patch_data_connector_with_invalid_namespace(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers, member_1_user: UserInfo
) -> None:
    namespace = member_1_user.namespace.path.serialize()
    _, response = await sanic_client.get(f"/api/data/namespaces/{namespace}", headers=user_headers)
    assert response.status_code == 200, response.text
    data_connector = await create_data_connector("My data connector")

    headers = merge_headers(user_headers, {"If-Match": data_connector["etag"]})
    patch = {
        "namespace": namespace,
    }
    data_connector_id = data_connector["id"]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}", headers=headers, json=patch
    )

    assert response.status_code == 404, response.text
    assert "you do not have sufficient permissions" in response.json["error"]["message"]


@pytest.mark.asyncio
async def test_patch_data_connector_as_editor(
    sanic_client: SanicASGITestClient,
    create_data_connector,
    admin_headers,
    admin_user,
    user_headers,
    regular_user,
) -> None:
    _, response = await sanic_client.post(
        "/api/data/groups", headers=admin_headers, json={"name": "My Group", "slug": "my-group"}
    )
    assert response.status_code == 201, response.text
    patch = [{"id": regular_user.id, "role": "editor"}]
    _, response = await sanic_client.patch("/api/data/groups/my-group/members", headers=admin_headers, json=patch)
    assert response.status_code == 200, response.text
    data_connector = await create_data_connector(
        "My data connector", user=admin_user, headers=admin_headers, namespace="my-group"
    )
    data_connector_id = data_connector["id"]

    headers = merge_headers(user_headers, {"If-Match": data_connector["etag"]})
    patch = {
        # Test that we do not require DELETE permission when sending the current namepace
        "namespace": data_connector["namespace"],
        # Test that we do not require DELETE permission when sending the current visibility
        "visibility": data_connector["visibility"],
        "description": "A new description",
    }
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}", headers=headers, json=patch
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json.get("namespace") == data_connector["namespace"]
    assert response.json.get("visibility") == data_connector["visibility"]
    assert response.json.get("description") == "A new description"


@pytest.mark.asyncio
async def test_patch_data_connector_slug(
    sanic_client: SanicASGITestClient,
    create_data_connector,
    user_headers,
) -> None:
    await create_data_connector("Data connector 1")
    await create_data_connector("Data connector 2")
    data_connector = await create_data_connector("My data connector")
    data_connector_id = data_connector["id"]
    namespace = data_connector["namespace"]
    old_slug = data_connector["slug"]
    await create_data_connector("Data connector 3")

    # Patch a data connector
    headers = merge_headers(user_headers, {"If-Match": data_connector["etag"]})
    new_slug = "some-updated-slug"
    patch = {"slug": new_slug}
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}", headers=headers, json=patch
    )

    assert response.status_code == 200, response.text

    # Check that the data connector's slug has been updated
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}", headers=user_headers)
    assert response.status_code == 200, response.text
    data_connector = response.json
    assert data_connector["id"] == data_connector_id
    assert data_connector["name"] == "My data connector"
    assert data_connector["namespace"] == namespace
    assert data_connector["slug"] == new_slug

    # Check that we can get the data connector with the new slug
    _, response = await sanic_client.get(
        f"/api/data/namespaces/{namespace}/data_connectors/{new_slug}", headers=user_headers
    )
    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json.get("id") == data_connector_id
    assert data_connector["namespace"] == namespace
    assert data_connector["slug"] == new_slug

    # Check that we can get the data connector with the old slug
    _, response = await sanic_client.get(
        f"/api/data/namespaces/{namespace}/data_connectors/{old_slug}", headers=user_headers
    )
    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json.get("id") == data_connector_id
    assert data_connector["namespace"] == namespace
    assert data_connector["slug"] == new_slug


@pytest.mark.asyncio
async def test_patch_global_data_connector(
    sanic_client: SanicASGITestClient,
    user_headers: dict[str, str],
    admin_headers: dict[str, str],
    monkeypatch: "MonkeyPatch",
) -> None:
    # The DOI resolver seems to block requests from GitHub action runners, so we mock its response
    metadata = RCloneDOIMetadata(
        DOI="10.5281/zenodo.2600782",
        URL="https://doi.org/10.5281/zenodo.2600782",
        metadataURL="https://zenodo.org/api/records/3542869",
        provider="zenodo",
    )
    _mock_get_doi_metadata(metadata=metadata, sanic_client=sanic_client, monkeypatch=monkeypatch)
    zenodo_metadata = DOIMetadata(
        name="SwissDataScienceCenter/renku-python: Version 0.7.2",
        description="""<a href="https://github.com/SwissDataScienceCenter/renku-python/compare/v0.7.1...v0.7.2">0.7.2</a> (2019-11-15)\nBug Fixes\n<ul>\n<li>ensure all Person instances have valid ids (<a href="https://github.com/SwissDataScienceCenter/renku-python/commit/85585d0">85585d0</a>), addresses <a href="https://github.com/SwissDataScienceCenter/renku-python/issues/812">#812</a></li>\n</ul>""",  # noqa E501
        keywords=[],
    )
    _mock_get_dataset_metadata(metadata=zenodo_metadata, sanic_client=sanic_client, monkeypatch=monkeypatch)

    doi = "10.5281/zenodo.2600782"
    payload = {
        "storage": {
            "configuration": {"type": "doi", "doi": doi},
            "source_path": "",
            "target_path": "",
        },
    }

    _, response = await sanic_client.post("/api/data/data_connectors/global", headers=user_headers, json=payload)

    assert response.status_code == 201, response.text
    assert response.json is not None
    data_connector = response.json
    data_connector_id = data_connector["id"]
    assert data_connector.get("name") == "SwissDataScienceCenter/renku-python: Version 0.7.2"

    # Check that a regular user cannot patch a global data connector
    headers = merge_headers(user_headers, {"If-Match": data_connector["etag"]})
    payload = {"name": "New name", "description": "new description"}

    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}", headers=headers, json=payload
    )

    assert response.status_code == 404, response.text

    # Check that an admin user can delete a global data connector
    headers = merge_headers(admin_headers, {"If-Match": data_connector["etag"]})

    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}", headers=headers, json=payload
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json.get("id") == data_connector_id
    assert response.json.get("name") == "New name"
    assert response.json.get("slug") == data_connector["slug"]
    assert response.json.get("description") == "new description"
    assert response.json.get("storage") == data_connector["storage"]


@pytest.mark.asyncio
async def test_delete_data_connector(sanic_client: SanicASGITestClient, create_data_connector, user_headers) -> None:
    await create_data_connector("Data connector 1")
    data_connector = await create_data_connector("Data connector 2")
    await create_data_connector("Data connector 3")

    data_connector_id = data_connector["id"]
    _, response = await sanic_client.delete(f"/api/data/data_connectors/{data_connector_id}", headers=user_headers)

    assert response.status_code == 204, response.text

    _, response = await sanic_client.get("/api/data/data_connectors", headers=user_headers)

    assert response.status_code == 200, response.text
    assert {dc["name"] for dc in response.json} == {"Data connector 1", "Data connector 3"}


@pytest.mark.asyncio
async def test_delete_global_data_connector(
    sanic_client: SanicASGITestClient,
    user_headers: dict[str, str],
    admin_headers: dict[str, str],
    monkeypatch: "MonkeyPatch",
) -> None:
    # The DOI resolver seems to block requests from GitHub action runners, so we mock its response
    metadata = RCloneDOIMetadata(
        DOI="10.5281/zenodo.2600782",
        URL="https://doi.org/10.5281/zenodo.2600782",
        metadataURL="https://zenodo.org/api/records/3542869",
        provider="zenodo",
    )
    _mock_get_doi_metadata(metadata=metadata, sanic_client=sanic_client, monkeypatch=monkeypatch)
    zenodo_metadata = DOIMetadata(
        name="SwissDataScienceCenter/renku-python: Version 0.7.2",
        description="""<a href="https://github.com/SwissDataScienceCenter/renku-python/compare/v0.7.1...v0.7.2">0.7.2</a> (2019-11-15)\nBug Fixes\n<ul>\n<li>ensure all Person instances have valid ids (<a href="https://github.com/SwissDataScienceCenter/renku-python/commit/85585d0">85585d0</a>), addresses <a href="https://github.com/SwissDataScienceCenter/renku-python/issues/812">#812</a></li>\n</ul>""",  # noqa E501
        keywords=[],
    )
    _mock_get_dataset_metadata(metadata=zenodo_metadata, sanic_client=sanic_client, monkeypatch=monkeypatch)

    doi = "10.5281/zenodo.2600782"
    payload = {
        "storage": {
            "configuration": {"type": "doi", "doi": doi},
            "source_path": "",
            "target_path": "",
        },
    }

    _, response = await sanic_client.post("/api/data/data_connectors/global", headers=user_headers, json=payload)

    assert response.status_code == 201, response.text
    assert response.json is not None
    data_connector = response.json
    data_connector_id = data_connector["id"]

    # Check that a regular user cannot delete a global data connector
    _, response = await sanic_client.delete(f"/api/data/data_connectors/{data_connector_id}", headers=user_headers)

    assert response.status_code == 404, response.text

    # Check that an admin user can delete a global data connector
    _, response = await sanic_client.delete(f"/api/data/data_connectors/{data_connector_id}", headers=admin_headers)

    assert response.status_code == 204, response.text

    _, response = await sanic_client.get("/api/data/data_connectors")

    assert response.status_code == 200, response.text
    assert {dc["name"] for dc in response.json} == set()


@pytest.mark.asyncio
async def test_get_data_connector_project_links_empty(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers
) -> None:
    data_connector = await create_data_connector("Data connector 1")

    data_connector_id = data_connector["id"]
    _, response = await sanic_client.get(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=user_headers
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert len(response.json) == 0


@pytest.mark.asyncio
async def test_post_data_connector_project_link(
    sanic_client: SanicASGITestClient, create_data_connector, create_project, user_headers
) -> None:
    data_connector = await create_data_connector("Data connector 1")
    project = await create_project("Project A")

    data_connector_id = data_connector["id"]
    project_id = project["id"]
    payload = {"project_id": project_id}
    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=user_headers, json=payload
    )

    assert response.status_code == 201, response.text
    assert response.json is not None
    link = response.json
    assert link.get("data_connector_id") == data_connector_id
    assert link.get("project_id") == project_id
    assert link.get("created_by") == "user"

    # Check that the links list from the data connector is not empty now
    _, response = await sanic_client.get(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=user_headers
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert len(response.json) == 1
    assert response.json[0].get("id") == link["id"]
    assert response.json[0].get("data_connector_id") == data_connector_id
    assert response.json[0].get("project_id") == project_id

    # Check that the links list to the project is not empty now
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/data_connector_links", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert len(response.json) == 1
    assert response.json[0].get("id") == link["id"]
    assert response.json[0].get("data_connector_id") == data_connector_id
    assert response.json[0].get("project_id") == project_id


@pytest.mark.asyncio
async def test_post_data_connector_project_link_already_exists(
    sanic_client: SanicASGITestClient, create_data_connector, create_project, user_headers
) -> None:
    data_connector = await create_data_connector("Data connector 1")
    project = await create_project("Project A")
    data_connector_id = data_connector["id"]
    project_id = project["id"]
    payload = {"project_id": project_id}
    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=user_headers, json=payload
    )
    assert response.status_code == 201, response.text

    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=user_headers, json=payload
    )
    assert response.status_code == 409, response.text


@pytest.mark.asyncio
async def test_post_data_connector_project_link_unauthorized_if_not_project_editor(
    sanic_client: SanicASGITestClient,
    create_data_connector,
    create_project,
    user_headers,
    member_1_headers,
    member_1_user,
) -> None:
    _, response = await sanic_client.post(
        "/api/data/groups", headers=user_headers, json={"name": "My Group", "slug": "my-group"}
    )
    assert response.status_code == 201, response.text
    patch = [{"id": member_1_user.id, "role": "owner"}]
    _, response = await sanic_client.patch("/api/data/groups/my-group/members", headers=user_headers, json=patch)
    assert response.status_code == 200
    data_connector = await create_data_connector("Data connector 1", namespace="my-group")
    data_connector_id = data_connector["id"]
    project = await create_project("Project A")
    project_id = project["id"]
    patch = [{"id": member_1_user.id, "role": "viewer"}]
    _, response = await sanic_client.patch(f"/api/data/projects/{project_id}/members", headers=user_headers, json=patch)
    assert response.status_code == 200, response.text

    # Check that "member_1" can view the project and data connector
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}", headers=member_1_headers)
    assert response.status_code == 200, response.text
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}", headers=member_1_headers)
    assert response.status_code == 200, response.text

    payload = {"project_id": project_id}
    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=member_1_headers, json=payload
    )

    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_post_data_connector_project_link_succeeds_if_not_data_connector_editor(
    sanic_client: SanicASGITestClient,
    create_data_connector,
    create_project,
    user_headers,
    member_1_headers,
    member_1_user,
) -> None:
    _, response = await sanic_client.post(
        "/api/data/groups", headers=user_headers, json={"name": "My Group", "slug": "my-group"}
    )
    assert response.status_code == 201, response.text
    patch = [{"id": member_1_user.id, "role": "viewer"}]
    _, response = await sanic_client.patch("/api/data/groups/my-group/members", headers=user_headers, json=patch)
    assert response.status_code == 200
    data_connector = await create_data_connector("Data connector 1", namespace="my-group")
    data_connector_id = data_connector["id"]
    project = await create_project("Project A")
    project_id = project["id"]
    patch = [{"id": member_1_user.id, "role": "owner"}]
    _, response = await sanic_client.patch(f"/api/data/projects/{project_id}/members", headers=user_headers, json=patch)
    assert response.status_code == 200, response.text

    # Check that "member_1" can view the project and data connector
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}", headers=member_1_headers)
    assert response.status_code == 200, response.text
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}", headers=member_1_headers)
    assert response.status_code == 200, response.text

    payload = {"project_id": project_id}
    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=member_1_headers, json=payload
    )

    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_post_data_connector_project_link_public_data_connector(
    sanic_client: SanicASGITestClient,
    create_data_connector,
    create_project,
    user_headers,
    member_1_headers,
    member_1_user,
    app_manager,
) -> None:
    data_connector = await create_data_connector(
        "Data connector 1", user=member_1_user, headers=member_1_headers, visibility="public"
    )
    data_connector_id = data_connector["id"]
    project = await create_project("Project A")
    project_id = project["id"]

    # Check that "regular_user" can view the project and data connector
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}", headers=user_headers)
    assert response.status_code == 200, response.text
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}", headers=user_headers)
    assert response.status_code == 200, response.text

    payload = {"project_id": project_id}
    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=user_headers, json=payload
    )

    assert response.status_code == 201, response.text
    assert response.json is not None
    link = response.json
    assert link.get("data_connector_id") == data_connector_id
    assert link.get("project_id") == project_id
    assert link.get("created_by") == "user"
    app_manager.metrics.data_connector_linked.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("project_role", ["viewer", "editor", "owner"])
async def test_post_data_connector_project_link_doesnt_extend_read_access(
    sanic_client: SanicASGITestClient,
    create_data_connector,
    create_project,
    user_headers,
    member_1_headers,
    member_1_user,
    project_role,
) -> None:
    data_connector = await create_data_connector("Data connector 1")
    data_connector_id = data_connector["id"]
    project = await create_project("Project A")
    project_id = project["id"]
    patch = [{"id": member_1_user.id, "role": project_role}]
    _, response = await sanic_client.patch(f"/api/data/projects/{project_id}/members", headers=user_headers, json=patch)
    assert response.status_code == 200, response.text

    # Check that "member_1" can view the project
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}", headers=member_1_headers)
    assert response.status_code == 200, response.text
    # Check that "member_1" cannot view the data connector
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}", headers=member_1_headers)
    assert response.status_code == 404, response.text

    data_connector_id = data_connector["id"]
    project_id = project["id"]
    payload = {"project_id": project_id}
    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=user_headers, json=payload
    )
    assert response.status_code == 201, response.text

    # Check that "member_1" still cannot view the data connector
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}", headers=member_1_headers)
    assert response.status_code == 404, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("group_role", ["viewer", "editor", "owner"])
async def test_post_data_connector_project_link_does_not_extend_access_to_parent_group_members(
    sanic_client: SanicASGITestClient,
    create_data_connector,
    user_headers,
    member_1_headers,
    member_1_user,
    group_role,
) -> None:
    data_connector = await create_data_connector("Data connector 1")
    data_connector_id = data_connector["id"]
    _, response = await sanic_client.post(
        "/api/data/groups", headers=user_headers, json={"name": "My Group", "slug": "my-group"}
    )
    assert response.status_code == 201, response.text
    patch = [{"id": member_1_user.id, "role": group_role}]
    _, response = await sanic_client.patch("/api/data/groups/my-group/members", headers=user_headers, json=patch)
    assert response.status_code == 200
    payload = {"name": "Project A", "namespace": "my-group"}
    _, response = await sanic_client.post("/api/data/projects", headers=user_headers, json=payload)
    assert response.status_code == 201
    project = response.json
    project_id = project["id"]

    # Check that "member_1" can view the project
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}", headers=member_1_headers)
    assert response.status_code == 200, response.text
    # Check that "member_1" cannot view the data connector
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}", headers=member_1_headers)
    assert response.status_code == 404, response.text

    data_connector_id = data_connector["id"]
    project_id = project["id"]
    payload = {"project_id": project_id}
    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=user_headers, json=payload
    )
    assert response.status_code == 201, response.text

    # Check that "member_1" can still not view the data connector
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}", headers=member_1_headers)
    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_delete_data_connector_project_link(
    sanic_client: SanicASGITestClient, create_data_connector, create_project, user_headers
) -> None:
    data_connector = await create_data_connector("Data connector 1")
    project = await create_project("Project A")
    data_connector_id = data_connector["id"]
    project_id = project["id"]
    payload = {"project_id": project_id}
    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=user_headers, json=payload
    )
    assert response.status_code == 201, response.text
    link = response.json

    _, response = await sanic_client.delete(
        f"/api/data/data_connectors/{data_connector_id}/project_links/{link['id']}", headers=user_headers
    )

    assert response.status_code == 204, response.text

    # Check that the links list from the data connector is empty now
    _, response = await sanic_client.get(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=user_headers
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert len(response.json) == 0

    # Check that the links list to the project is empty now
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/data_connector_links", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert len(response.json) == 0

    # Check that calling delete again returns a 204
    _, response = await sanic_client.delete(
        f"/api/data/data_connectors/{data_connector_id}/project_links/{link['id']}", headers=user_headers
    )

    assert response.status_code == 204, response.text


@pytest.mark.asyncio
async def test_delete_data_connector_after_linking(
    sanic_client: SanicASGITestClient, create_data_connector, create_project, user_headers
) -> None:
    data_connector = await create_data_connector("Data connector 1")
    project = await create_project("Project A")
    data_connector_id = data_connector["id"]
    project_id = project["id"]
    payload = {"project_id": project_id}
    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=user_headers, json=payload
    )
    assert response.status_code == 201, response.text

    _, response = await sanic_client.delete(f"/api/data/data_connectors/{data_connector_id}", headers=user_headers)

    assert response.status_code == 204, response.text

    # Check that the project still exists
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}", headers=user_headers)
    assert response.status_code == 200, response.text

    # Check that the links list to the project is empty now
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/data_connector_links", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert len(response.json) == 0


@pytest.mark.asyncio
async def test_delete_project_after_linking(
    sanic_client: SanicASGITestClient, create_data_connector, create_project, user_headers
) -> None:
    data_connector = await create_data_connector("Data connector 1")
    project = await create_project("Project A")
    data_connector_id = data_connector["id"]
    project_id = project["id"]
    payload = {"project_id": project_id}
    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=user_headers, json=payload
    )
    assert response.status_code == 201, response.text

    _, response = await sanic_client.delete(f"/api/data/projects/{project_id}", headers=user_headers)

    assert response.status_code == 204, response.text

    # Check that the data connector still exists
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}", headers=user_headers)

    assert response.status_code == 200, response.text

    # Check that the links list from the data connector is empty now
    _, response = await sanic_client.get(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=user_headers
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert len(response.json) == 0


@pytest.mark.asyncio
async def test_patch_data_connector_secrets(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers
) -> None:
    data_connector = await create_data_connector("My data connector")
    data_connector_id = data_connector["id"]

    payload = [
        {"name": "access_key_id", "value": "access key id value"},
        {"name": "secret_access_key", "value": "secret access key value"},
    ]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}/secrets", headers=user_headers, json=payload
    )

    assert response.status_code == 200, response.json
    assert response.json is not None
    secrets = response.json
    assert len(secrets) == 2
    assert {s["name"] for s in secrets} == {"access_key_id", "secret_access_key"}

    # Check that the secrets are returned from a GET request
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}/secrets", headers=user_headers)
    assert response.status_code == 200, response.json
    assert response.json is not None
    secrets = response.json
    assert len(secrets) == 2
    assert {s["name"] for s in secrets} == {"access_key_id", "secret_access_key"}

    # Check that the data connector is referenced from the first user secret
    user_secret_id = secrets[0]["secret_id"]
    _, response = await sanic_client.get(f"/api/data/user/secrets/{user_secret_id}", headers=user_headers)
    assert response.status_code == 200, response.json
    assert response.json is not None
    assert response.json.get("data_connector_ids") is not None
    assert {id for id in response.json.get("data_connector_ids")} == {data_connector_id}


@pytest.mark.asyncio
async def test_patch_data_connector_secrets_update_secrets(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers
) -> None:
    data_connector = await create_data_connector("My data connector")
    data_connector_id = data_connector["id"]
    payload = [
        {"name": "access_key_id", "value": "access key id value"},
        {"name": "secret_access_key", "value": "secret access key value"},
    ]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}/secrets", headers=user_headers, json=payload
    )
    assert response.status_code == 200, response.json
    assert response.json is not None
    secrets = response.json
    assert len(secrets) == 2
    assert {s["name"] for s in secrets} == {"access_key_id", "secret_access_key"}
    secret_ids = {s["secret_id"] for s in secrets}

    payload = [
        {"name": "access_key_id", "value": "new access key id value"},
        {"name": "secret_access_key", "value": "new secret access key value"},
    ]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}/secrets", headers=user_headers, json=payload
    )

    assert response.status_code == 200, response.json
    assert response.json is not None
    secrets = response.json
    assert len(secrets) == 2
    assert {s["name"] for s in secrets} == {"access_key_id", "secret_access_key"}
    assert {s["secret_id"] for s in secrets} == secret_ids

    # Check that the secrets are returned from a GET request
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}/secrets", headers=user_headers)
    assert response.status_code == 200, response.json
    assert response.json is not None
    secrets = response.json
    assert len(secrets) == 2
    assert {s["name"] for s in secrets} == {"access_key_id", "secret_access_key"}
    assert {s["secret_id"] for s in secrets} == secret_ids


@pytest.mark.asyncio
async def test_patch_data_connector_secrets_add_and_remove_secrets(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers
) -> None:
    data_connector = await create_data_connector("My data connector")
    data_connector_id = data_connector["id"]
    payload = [
        {"name": "access_key_id", "value": "access key id value"},
        {"name": "secret_access_key", "value": "secret access key value"},
    ]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}/secrets", headers=user_headers, json=payload
    )
    assert response.status_code == 200, response.json
    assert response.json is not None
    secrets = response.json
    assert len(secrets) == 2
    assert {s["name"] for s in secrets} == {"access_key_id", "secret_access_key"}
    access_key_id_secret_id = next(filter(lambda s: s["name"] == "access_key_id", secrets), None)

    payload = [
        {"name": "access_key_id", "value": "new access key id value"},
        {"name": "secret_access_key", "value": None},
        {"name": "sse_kms_key_id", "value": "password"},
    ]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}/secrets", headers=user_headers, json=payload
    )

    assert response.status_code == 200, response.json
    assert response.json is not None
    secrets = response.json
    assert len(secrets) == 2
    assert {s["name"] for s in secrets} == {"access_key_id", "sse_kms_key_id"}
    new_access_key_id_secret_id = next(filter(lambda s: s["name"] == "access_key_id", secrets), None)
    assert new_access_key_id_secret_id == access_key_id_secret_id

    # Check that the secrets are returned from a GET request
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}/secrets", headers=user_headers)
    assert response.status_code == 200, response.json
    assert response.json is not None
    secrets = response.json
    assert len(secrets) == 2
    assert {s["name"] for s in secrets} == {"access_key_id", "sse_kms_key_id"}

    # Check the associated secrets
    _, response = await sanic_client.get("/api/data/user/secrets", params={"kind": "storage"}, headers=user_headers)
    assert response.status_code == 200
    assert response.json is not None
    assert len(response.json) == 2
    assert {s["name"] for s in secrets} == {"access_key_id", "sse_kms_key_id"}


@pytest.mark.asyncio
async def test_delete_data_connector_secrets(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers
) -> None:
    data_connector = await create_data_connector("My data connector")
    data_connector_id = data_connector["id"]
    payload = [
        {"name": "access_key_id", "value": "access key id value"},
        {"name": "secret_access_key", "value": "secret access key value"},
    ]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}/secrets", headers=user_headers, json=payload
    )
    assert response.status_code == 200, response.json
    assert response.json is not None
    secrets = response.json
    assert len(secrets) == 2
    assert {s["name"] for s in secrets} == {"access_key_id", "secret_access_key"}

    _, response = await sanic_client.delete(
        f"/api/data/data_connectors/{data_connector_id}/secrets", headers=user_headers
    )

    assert response.status_code == 204, response.json

    # Check that the secrets list is empty from the GET request
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}/secrets", headers=user_headers)
    assert response.status_code == 200, response.json
    assert response.json == [], response.json

    # Check that the associated secrets are deleted
    _, response = await sanic_client.get("/api/data/user/secrets", params={"kind": "storage"}, headers=user_headers)

    assert response.status_code == 200
    assert response.json == [], response.json


@pytest.mark.myskip(1 == 1, reason="Depends on a remote openBIS host which may not always be available.")
@pytest.mark.asyncio
async def test_create_openbis_data_connector(sanic_client, create_openbis_data_connector, user_headers) -> None:
    openbis_session_token = await get_openbis_session_token(
        host="openbis-eln-lims.ethz.ch",  # Public openBIS demo instance.
        username="observer",
        password="1234",
    )
    data_connector = await create_openbis_data_connector(
        "openBIS data connector 1", session_token=openbis_session_token
    )
    data_connector_id = data_connector["id"]

    payload = [
        {"name": "session_token", "value": openbis_session_token},
    ]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}/secrets", headers=user_headers, json=payload
    )
    assert response.status_code == 200, response.json
    assert {s["name"] for s in response.json} == {"session_token"}
    created_secret_ids = {s["secret_id"] for s in response.json}
    assert len(created_secret_ids) == 1
    assert response.json[0].keys() == {"secret_id", "name"}


@pytest.mark.myskip(1 == 1, reason="Depends on a remote openBIS host which may not always be available.")
@pytest.mark.asyncio
async def test_create_openbis_data_connector_with_invalid_session_token(
    sanic_client, create_openbis_data_connector, user_headers
) -> None:
    invalid_openbis_session_token = "1234"
    data_connector = await create_openbis_data_connector("openBIS data connector 1", invalid_openbis_session_token)
    data_connector_id = data_connector["id"]

    payload = [
        {"name": "session_token", "value": invalid_openbis_session_token},
    ]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}/secrets", headers=user_headers, json=payload
    )
    assert response.status_code == 500, response.json
    assert response.json["error"]["message"] == "An openBIS personal access token related request failed."


@pytest.mark.asyncio
async def test_get_project_permissions_unauthorized(
    sanic_client, create_data_connector, admin_headers, admin_user, user_headers
) -> None:
    data_connector = await create_data_connector("My data connector", user=admin_user, headers=admin_headers)
    data_connector_id = data_connector["id"]

    _, response = await sanic_client.get(f"/api/data/projects/{data_connector_id}/permissions", headers=user_headers)

    assert response.status_code == 404, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["viewer", "editor", "owner"])
async def test_get_data_connector_permissions_cascading_from_group(
    sanic_client: SanicASGITestClient,
    create_data_connector,
    admin_headers,
    admin_user,
    user_headers,
    regular_user,
    role,
) -> None:
    _, response = await sanic_client.post(
        "/api/data/groups", headers=admin_headers, json={"name": "My Group", "slug": "my-group"}
    )
    assert response.status_code == 201, response.text
    patch = [{"id": regular_user.id, "role": role}]
    _, response = await sanic_client.patch("/api/data/groups/my-group/members", headers=admin_headers, json=patch)
    assert response.status_code == 200, response.text
    data_connector = await create_data_connector(
        "My data connector", user=admin_user, headers=admin_headers, namespace="my-group"
    )
    data_connector_id = data_connector["id"]

    expected_permissions = dict(
        write=False,
        delete=False,
        change_membership=False,
    )
    if role == "editor" or role == "owner":
        expected_permissions["write"] = True
    if role == "owner":
        expected_permissions["delete"] = True
        expected_permissions["change_membership"] = True

    _, response = await sanic_client.get(
        f"/api/data/data_connectors/{data_connector_id}/permissions", headers=user_headers
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    permissions = response.json
    assert permissions.get("write") == expected_permissions["write"]
    assert permissions.get("delete") == expected_permissions["delete"]
    assert permissions.get("change_membership") == expected_permissions["change_membership"]


@pytest.mark.asyncio
async def test_creating_dc_in_project(sanic_client, user_headers) -> None:
    # Create a group i.e. /test1
    payload = {
        "name": "test1",
        "slug": "test1",
        "description": "Group 1 Description",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text

    # Create a project in the group /test1/prj1
    payload = {
        "name": "prj1",
        "namespace": "test1",
        "slug": "prj1",
    }
    _, response = await sanic_client.post("/api/data/projects", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    project_id = response.json["id"]

    # Ensure there is only one project
    _, response = await sanic_client.get("/api/data/projects", headers=user_headers)
    assert response.status_code == 200, response.text
    assert len(response.json) == 1

    # Create a data connector in the project /test1/proj1/dc1
    dc_namespace = "test1/prj1"
    payload = {
        "name": "dc1",
        "namespace": dc_namespace,
        "slug": "dc1",
        "storage": {
            "configuration": {"type": "s3", "endpoint": "http://s3.aws.com"},
            "source_path": "giab",
            "target_path": "giab",
        },
    }
    _, response = await sanic_client.post("/api/data/data_connectors", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    assert response.json["namespace"] == dc_namespace
    dc_id = response.json["id"]

    # Ensure there is only one project
    _, response = await sanic_client.get("/api/data/projects", headers=user_headers)
    assert response.status_code == 200, response.text
    assert len(response.json) == 1

    # Ensure that you can list the data connector
    _, response = await sanic_client.get(f"/api/data/data_connectors/{dc_id}", headers=user_headers)
    assert response.status_code == 200, response.text

    # Link the data connector to the project
    payload = {"project_id": project_id}
    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{dc_id}/project_links", headers=user_headers, json=payload
    )
    assert response.status_code == 201, response.text

    # Ensure that you can see the data connector link
    _, response = await sanic_client.get(f"/api/data/data_connectors/{dc_id}/project_links", headers=user_headers)
    assert response.status_code == 200, response.text
    assert len(response.json) == 1
    dc_link = response.json[0]
    assert dc_link["project_id"] == project_id
    assert dc_link["data_connector_id"] == dc_id

    # Ensure that you can list data connectors
    _, response = await sanic_client.get("/api/data/data_connectors", headers=user_headers)
    assert response.status_code == 200, response.text
    assert len(response.json) == 1
    assert response.json[0]["namespace"] == dc_namespace


@pytest.mark.asyncio
async def test_creating_dc_in_project_no_leak_to_other_project(sanic_client, user_headers, member_1_headers) -> None:
    # Create a project owned by member_1
    payload = {
        "name": "Project 1",
        "namespace": "member-1.doe",
        "slug": "project-1",
    }
    _, res = await sanic_client.post("/api/data/projects", headers=member_1_headers, json=payload)
    assert res.status_code == 201, res.text

    payload = {
        "name": "Project 1",
        "namespace": "user.doe",
        "slug": "project-1",
    }
    _, res = await sanic_client.post("/api/data/projects", headers=user_headers, json=payload)
    assert res.status_code == 201, res.text
    project = res.json
    project_path = f"{project['namespace']}/{project['slug']}"

    payload = {
        "name": "My data connector",
        "namespace": project_path,
        "slug": "my-dc",
        "storage": {
            "configuration": {"type": "s3", "endpoint": "http://s3.aws.com"},
            "source_path": "giab",
            "target_path": "giab",
        },
    }
    _, res = await sanic_client.post("/api/data/data_connectors", headers=user_headers, json=payload)
    assert res.status_code == 201, res.text
    assert res.json is not None
    dc = res.json
    assert dc.get("id") is not None
    assert dc.get("name") == "My data connector"
    assert dc.get("namespace") == project_path
    assert dc.get("slug") == "my-dc"


@pytest.mark.asyncio
async def test_users_cannot_see_private_data_connectors_in_project(
    sanic_client,
    member_1_headers,
    member_2_user: UserInfo,
    member_2_headers,
    user_headers,
    regular_user: UserInfo,
) -> None:
    # Create a group i.e. /test1
    group_slug = "test1"
    payload = {
        "name": group_slug,
        "slug": group_slug,
        "description": "Group 1 Description",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=member_1_headers, json=payload)
    assert response.status_code == 201, response.text

    # Add member_2 as reader on the group
    payload = [
        {
            "id": member_2_user.id,
            "role": "viewer",
        }
    ]
    _, response = await sanic_client.patch(
        f"/api/data/groups/{group_slug}/members", headers=member_1_headers, json=payload
    )
    assert response.status_code == 200, response.text

    # Create a public project in the group /test1/prj1
    payload = {
        "name": "prj1",
        "namespace": "test1",
        "slug": "prj1",
        "visibility": "public",
    }
    _, response = await sanic_client.post("/api/data/projects", headers=member_1_headers, json=payload)
    assert response.status_code == 201, response.text
    project_id = response.json["id"]

    # Create a private data connector in the group
    dc_namespace = "test1"
    storage_config = {
        "configuration": {"type": "s3", "endpoint": "http://s3.aws.com"},
        "source_path": "giab",
        "target_path": "giab",
    }
    payload = {
        "name": "dc-private",
        "namespace": dc_namespace,
        "slug": "dc-private",
        "storage": storage_config,
        "visibility": "private",
    }
    _, response = await sanic_client.post("/api/data/data_connectors", headers=member_1_headers, json=payload)
    assert response.status_code == 201, response.text
    assert response.json["namespace"] == dc_namespace
    group_dc_id = response.json["id"]

    # Link the private data connector to the project
    payload = {"project_id": project_id}
    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{group_dc_id}/project_links", headers=member_1_headers, json=payload
    )
    assert response.status_code == 201, response.text

    # Create a data connector in the project /test1/proj1/dc1
    dc_namespace = "test1/prj1"
    payload = {
        "name": "dc1",
        "namespace": dc_namespace,
        "slug": "dc1",
        "storage": storage_config,
    }
    _, response = await sanic_client.post("/api/data/data_connectors", headers=member_1_headers, json=payload)
    assert response.status_code == 201, response.text
    assert response.json["namespace"] == dc_namespace
    project_dc_id = response.json["id"]

    # Link the data connector to the project
    payload = {"project_id": project_id}
    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{project_dc_id}/project_links", headers=member_1_headers, json=payload
    )
    assert response.status_code == 201, response.text

    # Ensure that member_1 and member_2 can see both data connectors and their links
    for req_headers in [member_1_headers, member_2_headers]:
        _, response = await sanic_client.get("/api/data/data_connectors", headers=req_headers)
        assert response.status_code == 200, response.text
        assert len(response.json) == 2
        assert response.json[0]["id"] == project_dc_id
        assert response.json[1]["id"] == group_dc_id
        _, response = await sanic_client.get(
            f"/api/data/projects/{project_id}/data_connector_links", headers=req_headers
        )
        assert len(response.json) == 2
        assert response.json[0]["data_connector_id"] == group_dc_id
        assert response.json[1]["data_connector_id"] == project_dc_id

    # The project is public so user should see it
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}", headers=user_headers)
    assert response.status_code == 200, response.text
    # User is not part of the project and the data connector is private so they should not see any data connectors
    _, response = await sanic_client.get("/api/data/data_connectors", headers=user_headers)
    assert response.status_code == 200, response.text
    assert len(response.json) == 0
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/data_connector_links", headers=user_headers)
    assert len(response.json) == 0

    # Anonymous users should see the project but not any of the DCs or the links
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}")
    assert response.status_code == 200, response.text
    _, response = await sanic_client.get("/api/data/data_connectors")
    assert response.status_code == 200, response.text
    assert len(response.json) == 0
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/data_connector_links")
    assert len(response.json) == 0

    # Add user to the project
    payload = [
        {
            "id": regular_user.id,
            "role": "viewer",
        }
    ]
    _, response = await sanic_client.patch(
        f"/api/data/projects/{project_id}/members", headers=member_1_headers, json=payload
    )
    assert response.status_code == 200, response.text

    # Now since the user is part of the project they should see only the project DC but not the private one from
    # the group that user does not have access to
    _, response = await sanic_client.get("/api/data/data_connectors", headers=user_headers)
    assert response.status_code == 200, response.text
    assert len(response.json) == 1
    assert response.json[0]["id"] == project_dc_id
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/data_connector_links", headers=user_headers)
    assert response.json[0]["data_connector_id"] == project_dc_id


@pytest.mark.asyncio
async def test_number_of_inaccessible_data_connector_links_in_project(
    sanic_client,
    member_1_user: UserInfo,
    member_1_headers,
    regular_user: UserInfo,
    user_headers,
) -> None:
    # Create a public project
    payload = {
        "name": "prj1",
        "namespace": member_1_user.namespace.path.serialize(),
        "slug": "prj1",
        "visibility": "public",
    }
    _, response = await sanic_client.post("/api/data/projects", headers=member_1_headers, json=payload)
    assert response.status_code == 201, response.text
    project_id = response.json["id"]

    # Add user to the project
    payload = [
        {
            "id": regular_user.id,
            "role": "viewer",
        }
    ]
    _, response = await sanic_client.patch(
        f"/api/data/projects/{project_id}/members", headers=member_1_headers, json=payload
    )
    assert response.status_code == 200, response.text

    # Create a private data connector in the project
    storage_config = {
        "configuration": {"type": "s3", "endpoint": "http://s3.aws.com"},
        "source_path": "giab",
        "target_path": "giab",
    }
    dc_namespace = f"{member_1_user.namespace.path.serialize()}/prj1"
    payload = {
        "name": "dc1",
        "namespace": dc_namespace,
        "slug": "dc1",
        "storage": storage_config,
        "visibility": "private",
    }
    _, response = await sanic_client.post("/api/data/data_connectors", headers=member_1_headers, json=payload)
    assert response.status_code == 201, response.text
    assert response.json["namespace"] == dc_namespace
    project_dc_id = response.json["id"]

    # Link the data connector to the project
    payload = {"project_id": project_id}
    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{project_dc_id}/project_links", headers=member_1_headers, json=payload
    )
    assert response.status_code == 201, response.text

    # Create a private data connector in the owner user namespace
    storage_config = {
        "configuration": {"type": "s3", "endpoint": "http://s3.aws.com"},
        "source_path": "giab",
        "target_path": "giab",
    }
    payload = {
        "name": "dc1",
        "namespace": member_1_user.namespace.path.serialize(),
        "slug": "dc1",
        "storage": storage_config,
        "visibility": "private",
    }
    _, response = await sanic_client.post("/api/data/data_connectors", headers=member_1_headers, json=payload)
    assert response.status_code == 201, response.text
    assert response.json["namespace"] == member_1_user.namespace.path.serialize()
    project_dc_id = response.json["id"]

    # Link the data connector to the project
    payload = {"project_id": project_id}
    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{project_dc_id}/project_links", headers=member_1_headers, json=payload
    )
    assert response.status_code == 201, response.text

    # Ensure that anonymous users cannot see both of the data connectors
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/inaccessible_data_connector_links")
    assert "count" in response.json
    assert response.json["count"] == 2
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/data_connector_links")
    assert len(response.json) == 0

    # Ensure that the owner gets a zero in their inaccessible data connectors count
    _, response = await sanic_client.get(
        f"/api/data/projects/{project_id}/inaccessible_data_connector_links", headers=member_1_headers
    )
    assert "count" in response.json
    assert response.json["count"] == 0
    _, response = await sanic_client.get(
        f"/api/data/projects/{project_id}/data_connector_links", headers=member_1_headers
    )
    assert len(response.json) == 2

    # Ensure that the project member can NOT see 1 DC - the owners private DC
    _, response = await sanic_client.get(
        f"/api/data/projects/{project_id}/inaccessible_data_connector_links", headers=user_headers
    )
    assert "count" in response.json
    assert response.json["count"] == 1
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/data_connector_links", headers=user_headers)
    assert len(response.json) == 1


@dataclass
class DataConnectorTestCase:
    ns_kind: NamespaceKind
    visibility: Visibility | None = None

    def __str__(self) -> str:
        if self.visibility:
            return f"<{self.ns_kind.value} {self.visibility.value}>"
        else:
            return f"<{self.ns_kind.value}>"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "origin,destination,dc_visibility",
    [
        # Moving from project namespace
        (
            DataConnectorTestCase(NamespaceKind.project, Visibility.PRIVATE),
            DataConnectorTestCase(NamespaceKind.project, Visibility.PUBLIC),
            Visibility.PRIVATE,
        ),
        (
            DataConnectorTestCase(NamespaceKind.project, Visibility.PUBLIC),
            DataConnectorTestCase(NamespaceKind.project, Visibility.PRIVATE),
            Visibility.PRIVATE,
        ),
        (
            DataConnectorTestCase(NamespaceKind.project, Visibility.PRIVATE),
            DataConnectorTestCase(NamespaceKind.project, Visibility.PUBLIC),
            Visibility.PUBLIC,
        ),
        (
            DataConnectorTestCase(NamespaceKind.project, Visibility.PUBLIC),
            DataConnectorTestCase(NamespaceKind.project, Visibility.PRIVATE),
            Visibility.PUBLIC,
        ),
        (
            DataConnectorTestCase(NamespaceKind.project, Visibility.PRIVATE),
            DataConnectorTestCase(NamespaceKind.group),
            Visibility.PRIVATE,
        ),
        (
            DataConnectorTestCase(NamespaceKind.project, Visibility.PUBLIC),
            DataConnectorTestCase(NamespaceKind.group),
            Visibility.PRIVATE,
        ),
        (
            DataConnectorTestCase(NamespaceKind.project, Visibility.PRIVATE),
            DataConnectorTestCase(NamespaceKind.group),
            Visibility.PUBLIC,
        ),
        (
            DataConnectorTestCase(NamespaceKind.project, Visibility.PUBLIC),
            DataConnectorTestCase(NamespaceKind.group),
            Visibility.PUBLIC,
        ),
        (
            DataConnectorTestCase(NamespaceKind.project, Visibility.PRIVATE),
            DataConnectorTestCase(NamespaceKind.user),
            Visibility.PRIVATE,
        ),
        (
            DataConnectorTestCase(NamespaceKind.project, Visibility.PUBLIC),
            DataConnectorTestCase(NamespaceKind.user),
            Visibility.PRIVATE,
        ),
        (
            DataConnectorTestCase(NamespaceKind.project, Visibility.PRIVATE),
            DataConnectorTestCase(NamespaceKind.user),
            Visibility.PUBLIC,
        ),
        (
            DataConnectorTestCase(NamespaceKind.project, Visibility.PUBLIC),
            DataConnectorTestCase(NamespaceKind.user),
            Visibility.PUBLIC,
        ),
        # Moving from user namespace
        (
            DataConnectorTestCase(NamespaceKind.user),
            DataConnectorTestCase(NamespaceKind.project, Visibility.PRIVATE),
            Visibility.PUBLIC,
        ),
        (
            DataConnectorTestCase(NamespaceKind.user),
            DataConnectorTestCase(NamespaceKind.project, Visibility.PUBLIC),
            Visibility.PUBLIC,
        ),
        (
            DataConnectorTestCase(NamespaceKind.user),
            DataConnectorTestCase(NamespaceKind.project, Visibility.PRIVATE),
            Visibility.PRIVATE,
        ),
        (
            DataConnectorTestCase(NamespaceKind.user),
            DataConnectorTestCase(NamespaceKind.project, Visibility.PUBLIC),
            Visibility.PRIVATE,
        ),
        (
            DataConnectorTestCase(NamespaceKind.user),
            DataConnectorTestCase(NamespaceKind.group),
            Visibility.PUBLIC,
        ),
        (
            DataConnectorTestCase(NamespaceKind.user),
            DataConnectorTestCase(NamespaceKind.group),
            Visibility.PUBLIC,
        ),
        (
            DataConnectorTestCase(NamespaceKind.user),
            DataConnectorTestCase(NamespaceKind.group),
            Visibility.PRIVATE,
        ),
        (
            DataConnectorTestCase(NamespaceKind.user),
            DataConnectorTestCase(NamespaceKind.group),
            Visibility.PRIVATE,
        ),
        # Moving from group namespace
        (
            DataConnectorTestCase(NamespaceKind.group),
            DataConnectorTestCase(NamespaceKind.project, Visibility.PRIVATE),
            Visibility.PUBLIC,
        ),
        (
            DataConnectorTestCase(NamespaceKind.group),
            DataConnectorTestCase(NamespaceKind.project, Visibility.PUBLIC),
            Visibility.PUBLIC,
        ),
        (
            DataConnectorTestCase(NamespaceKind.group),
            DataConnectorTestCase(NamespaceKind.project, Visibility.PRIVATE),
            Visibility.PRIVATE,
        ),
        (
            DataConnectorTestCase(NamespaceKind.group),
            DataConnectorTestCase(NamespaceKind.project, Visibility.PUBLIC),
            Visibility.PRIVATE,
        ),
        (
            DataConnectorTestCase(NamespaceKind.group),
            DataConnectorTestCase(NamespaceKind.group),
            Visibility.PRIVATE,
        ),
        (
            DataConnectorTestCase(NamespaceKind.group),
            DataConnectorTestCase(NamespaceKind.group),
            Visibility.PRIVATE,
        ),
        (
            DataConnectorTestCase(NamespaceKind.group),
            DataConnectorTestCase(NamespaceKind.group),
            Visibility.PUBLIC,
        ),
        (
            DataConnectorTestCase(NamespaceKind.group),
            DataConnectorTestCase(NamespaceKind.group),
            Visibility.PUBLIC,
        ),
        (
            DataConnectorTestCase(NamespaceKind.group),
            DataConnectorTestCase(NamespaceKind.user),
            Visibility.PRIVATE,
        ),
        (
            DataConnectorTestCase(NamespaceKind.group),
            DataConnectorTestCase(NamespaceKind.user),
            Visibility.PRIVATE,
        ),
        (
            DataConnectorTestCase(NamespaceKind.group),
            DataConnectorTestCase(NamespaceKind.user),
            Visibility.PUBLIC,
        ),
        (
            DataConnectorTestCase(NamespaceKind.group),
            DataConnectorTestCase(NamespaceKind.user),
            Visibility.PUBLIC,
        ),
    ],
    ids=lambda x: str(x),
)
async def test_move_data_connector(
    sanic_client: SanicASGITestClient,
    member_1_user: UserInfo,
    member_1_headers: dict,
    origin: DataConnectorTestCase,
    destination: DataConnectorTestCase,
    dc_visibility: Visibility,
) -> None:
    # Create origin namespace
    linked_project_id: str | None = None
    match origin.ns_kind:
        case NamespaceKind.group:
            payload = {
                "name": "origin",
                "slug": "origin",
            }
            _, response = await sanic_client.post("/api/data/groups", headers=member_1_headers, json=payload)
            assert response.status_code == 201, response.text
            origin_path = NamespacePath.from_strings(response.json["slug"])
        case NamespaceKind.user:
            origin_path = member_1_user.namespace.path
        case NamespaceKind.project:
            payload = {
                "name": "origin",
                "namespace": member_1_user.namespace.path.serialize(),
                "slug": "origin",
                "visibility": "public" if origin.visibility == Visibility.PUBLIC else "private",
            }
            _, response = await sanic_client.post("/api/data/projects", headers=member_1_headers, json=payload)
            assert response.status_code == 201, response.text
            origin_path = ProjectPath.from_strings(response.json["namespace"], response.json["slug"])
            linked_project_id = response.json["id"]

    # Create the destination namespace
    match destination.ns_kind:
        case NamespaceKind.group:
            payload = {
                "name": "destination",
                "slug": "destination",
            }
            _, response = await sanic_client.post("/api/data/groups", headers=member_1_headers, json=payload)
            assert response.status_code == 201, response.text
            destination_path = NamespacePath.from_strings(response.json["slug"])
            destination_id = response.json["id"]
        case NamespaceKind.user:
            destination_path = member_1_user.namespace.path
            destination_id = response.json["id"]
        case NamespaceKind.project:
            payload = {
                "name": "destination",
                "namespace": member_1_user.namespace.path.serialize(),
                "slug": "destination",
                "visibility": "public" if origin.visibility == Visibility.PUBLIC else "private",
            }
            _, response = await sanic_client.post("/api/data/projects", headers=member_1_headers, json=payload)
            assert response.status_code == 201, response.text
            destination_path = ProjectPath.from_strings(response.json["namespace"], response.json["slug"])
            destination_id = response.json["id"]

    # Create the data connector
    response = await create_data_connector(
        sanic_client, member_1_headers, origin_path.serialize(), "dc1", private=dc_visibility == Visibility.PRIVATE
    )
    assert response.status_code == 201, response.text
    assert response.json["namespace"] == origin_path.serialize()
    dc_id = response.json["id"]
    dc_etag = response.json["etag"]

    # Create a project to link the DC to if the origin is not project
    if not isinstance(origin_path, ProjectPath):
        payload = {
            "name": "dc_link_project",
            "namespace": member_1_user.namespace.path.serialize(),
            "slug": "dc_link_project",
            "visibility": "private",
        }
        _, response = await sanic_client.post("/api/data/projects", headers=member_1_headers, json=payload)
        assert response.status_code == 201, response.text
        linked_project_id = response.json["id"]

    # Link the data connector a project
    payload = {"project_id": linked_project_id}
    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{dc_id}/project_links", headers=member_1_headers, json=payload
    )
    assert response.status_code == 201, response.text

    # Move the data connector
    payload = {"namespace": destination_path.serialize()}
    headers = merge_headers(member_1_headers, {"If-Match": dc_etag})
    _, response = await sanic_client.patch(f"/api/data/data_connectors/{dc_id}", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    assert response.json["namespace"] == destination_path.serialize()
    assert response.json["visibility"] == dc_visibility.value

    # Check the data connector link remains unchaged after moving
    _, response = await sanic_client.get(
        f"/api/data/projects/{linked_project_id}/data_connector_links", headers=headers
    )
    assert response.status_code == 200, response.text
    assert len(response.json) == 1
    assert response.json[0]["data_connector_id"] == dc_id

    # Moving the data connector to the new project creates a link to it automatically
    if isinstance(destination_path, ProjectPath):
        _, response = await sanic_client.get(
            f"/api/data/projects/{destination_id}/data_connector_links", headers=headers
        )
        assert response.status_code == 200, response.text
        assert len(response.json) == 1
        assert response.json[0]["data_connector_id"] == dc_id

    # Check that the number of namespaces is as expected
    _, response = await sanic_client.get(
        "/api/data/namespaces", headers=headers, params=dict(kinds=["group", "user", "project"], minimum_role="owner")
    )
    assert response.status_code == 200, response.text
    match origin.ns_kind, destination.ns_kind:
        case NamespaceKind.group, NamespaceKind.project:
            # The namespaces are the group, the project, the linked dc project and the user
            expected_namespaces = 4
        case NamespaceKind.group, NamespaceKind.group:
            # The namespaces are the 2 groups, the linked dc project and the user
            expected_namespaces = 4
        case NamespaceKind.project, NamespaceKind.user:
            # There is no new namespaces for linked project or for the destination user namespace
            expected_namespaces = 2
        case _:
            # The user, the source and the destination namespace
            expected_namespaces = 3
    assert len(response.json) == expected_namespaces


def test_description_cleanup() -> None:
    description_html = """<h1>A description</h1>
    <p>Some more text...</p>
    """

    description_text = core._html_to_text(description_html)

    expected = """A description\nSome more text..."""
    assert description_text == expected


def _mock_get_doi_metadata(metadata: RCloneDOIMetadata, sanic_client: SanicASGITestClient, monkeypatch: "MonkeyPatch"):
    """Mock the RCloneValidator.get_doi_metadata method."""

    # The DOI resolver seems to block requests from GitHub action runners, so we mock its response
    validator = sanic_client.sanic_app.ctx._dependencies.r_clone_validator
    _orig_get_doi_metadata = validator.get_doi_metadata

    async def _mock_get_doi_metadata(*args, **kwargs) -> RCloneDOIMetadata:
        doi_metadata = await _orig_get_doi_metadata(*args, **kwargs)
        if doi_metadata is not None:
            assert doi_metadata == metadata
            return doi_metadata

        warnings.warn("Could not retrieve DOI metadata, returning saved one", stacklevel=2)
        return metadata

    monkeypatch.setattr(validator, "get_doi_metadata", _mock_get_doi_metadata)


def _mock_get_dataset_metadata(metadata: DOIMetadata, sanic_client: SanicASGITestClient, monkeypatch: "MonkeyPatch"):
    """Mock the _get_dataset_metadata_invenio method."""

    # The Zenodo API may be unresponsive, so we mock its response
    from renku_data_services.data_connectors.doi import metadata as metadata_mod

    _orig_get_dataset_metadata_invenio = metadata_mod._get_dataset_metadata_invenio
    _orig_get_dataset_metadata_dataverse = metadata_mod._get_dataset_metadata_dataverse

    def _mock_get_dataset_metadata(original_fn):
        async def _mock(*args, **kwargs) -> DOIMetadata | None:
            fetched_metadata = await original_fn(*args, **kwargs)
            if fetched_metadata is not None:
                assert fetched_metadata == metadata
                return fetched_metadata

            warnings.warn("Could not retrieve DOI metadata, returning saved one", stacklevel=2)
            return metadata

        return _mock

    monkeypatch.setattr(
        metadata_mod, "_get_dataset_metadata_invenio", _mock_get_dataset_metadata(_orig_get_dataset_metadata_invenio)
    )
    monkeypatch.setattr(
        metadata_mod,
        "_get_dataset_metadata_dataverse",
        _mock_get_dataset_metadata(_orig_get_dataset_metadata_dataverse),
    )
