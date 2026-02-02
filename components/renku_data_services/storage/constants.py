"""Constants for storage."""

from dataclasses import dataclass
from typing import Final

ENVIDAT_V1_PROVIDER: Final[str] = "envidat_v1"
# TODO: where is this constants used?
# SCICAT_V1_PROVIDER: Final[str] = "scicat_v1"


@dataclass(frozen=True, eq=True, kw_only=True)
class StorageConfig:
    """Represents the configuration for an RClone storage."""

    allowed: bool
    """Whether the storage type is allowed or not."""

    options: dict[str, bool] | None = None
    """Maps each option name to whether it is allowed or not."""


# Each storage type is preceded by the rationale.
# Disallowed options are also preceded by the rationale.
STORAGE_CONFIG: Final[dict[str, StorageConfig]] = {
    # "alias" refers to other rclone configs
    "alias": StorageConfig(allowed=False),
    # Allow azureblob
    "azureblob": StorageConfig(
        allowed=True,
        options={
            "account": True,
            "env_auth": True,
            "key": True,
            "sas_url": True,
            "tenant": True,
            "client_id": True,
            "client_secret": True,
            # Path to a local file
            "client_certificate_path": False,
            # Related to above option
            "client_certificate_password": False,
            "client_send_certificate_chain": True,
            "username": True,
            "password": True,
            # Path to a local file
            "service_principal_file": False,
            "disable_instance_discovery": True,
            "use_msi": True,
            "msi_object_id": True,
            "msi_client_id": True,
            "msi_mi_res_id": True,
            "use_emulator": True,
            "use_az": True,
            "endpoint": True,
            "upload_cutoff": True,
            "chunk_size": True,
            "upload_concurrency": True,
            "copy_cutoff": True,
            "copy_concurrency": True,
            "use_copy_blob": True,
            "list_chunk": True,
            "access_tier": True,
            "archive_tier_delete": True,
            "disable_checksum": True,
            "memory_pool_flush_time": True,
            "memory_pool_use_mmap": True,
            "encoding": True,
            "public_access": True,
            "directory_markers": True,
            "no_check_container": True,
            "no_head_object": True,
            "delete_snapshots": True,
            "description": True,
        },
    ),
    # Not validated
    "azurefiles": StorageConfig(allowed=False),
    # Not validated
    "b2": StorageConfig(allowed=False),
    # Not validated
    "box": StorageConfig(allowed=False),
    # "cache" refers to other rclone configs
    "cache": StorageConfig(allowed=False),
    # "chunker" refers to other rclone configs
    "chunker": StorageConfig(allowed=False),
    # Not validated
    "cloudinary": StorageConfig(allowed=False),
    # "combine" refers to other rclone configs
    "combine": StorageConfig(allowed=False),
    # "compress" refers to other rclone configs
    "compress": StorageConfig(allowed=False),
    # "crypt" refers to other rclone configs
    "crypt": StorageConfig(allowed=False),
    # Allow doi
    "doi": StorageConfig(
        allowed=True, options={"doi": True, "provider": True, "doi_resolver_api_url": True, "description": True}
    ),
    # Allow drive
    "drive": StorageConfig(
        allowed=True,
        options={
            "client_id": True,
            "client_secret": True,
            "token": True,
            "auth_url": True,
            "token_url": True,
            "client_credentials": True,
            "scope": True,
            "root_folder_id": True,
            # Path to a local file
            "service_account_file": False,
            "service_account_credentials": True,
            "team_drive": True,
            "auth_owner_only": True,
            "use_trash": True,
            "copy_shortcut_content": True,
            "skip_gdocs": True,
            "show_all_gdocs": True,
            "skip_checksum_gphotos": True,
            "shared_with_me": True,
            "trashed_only": True,
            "starred_only": True,
            "formats": True,
            "export_formats": True,
            "import_formats": True,
            "allow_import_name_change": True,
            "use_created_date": True,
            "use_shared_date": True,
            "list_chunk": True,
            "impersonate": True,
            "alternate_export": True,
            "upload_cutoff": True,
            "chunk_size": True,
            "acknowledge_abuse": True,
            "keep_revision_forever": True,
            "size_as_quota": True,
            "v2_download_min_size": True,
            "pacer_min_sleep": True,
            "pacer_burst": True,
            "server_side_across_configs": True,
            "disable_http2": True,
            "stop_on_upload_limit": True,
            "stop_on_download_limit": True,
            "skip_shortcuts": True,
            "skip_dangling_shortcuts": True,
            "resource_key": True,
            "fast_list_bug_fix": True,
            "metadata_owner": True,
            "metadata_permissions": True,
            "metadata_labels": True,
            "encoding": True,
            "env_auth": True,
            "description": True,
        },
    ),
    # Allow dropbox
    "dropbox": StorageConfig(
        allowed=True,
        options={
            "client_id": True,
            "client_secret": True,
            "token": True,
            "auth_url": True,
            "token_url": True,
            "client_credentials": True,
            "chunk_size": True,
            "impersonate": True,
            "shared_files": True,
            "shared_folders": True,
            "pacer_min_sleep": True,
            "encoding": True,
            "root_namespace": True,
            "export_formats": True,
            "skip_exports": True,
            "show_all_exports": True,
            "batch_mode": True,
            "batch_size": True,
            "batch_timeout": True,
            "batch_commit_timeout": True,
            "description": True,
        },
    ),
    # Not validated
    "fichier": StorageConfig(allowed=False),
    # Not validated
    "filefabric": StorageConfig(allowed=False),
    # Not validated
    "filelu": StorageConfig(allowed=False),
    # Not validated
    "filescom": StorageConfig(allowed=False),
    # Allow ftp
    "ftp": StorageConfig(
        allowed=True,
        options={
            "host": True,
            "user": True,
            "port": True,
            "pass": True,
            "tls": True,
            "explicit_tls": True,
            "concurrency": True,
            "no_check_certificate": True,
            "disable_epsv": True,
            "disable_mlsd": True,
            "disable_utf8": True,
            "writing_mdtm": True,
            "force_list_hidden": True,
            "idle_timeout": True,
            "close_timeout": True,
            "tls_cache_size": True,
            "disable_tls13": True,
            "allow_insecure_tls_ciphers": True,
            "shut_timeout": True,
            "ask_password": True,
            "socks_proxy": True,
            "http_proxy": True,
            "no_check_upload": True,
            "encoding": True,
            "description": True,
        },
    ),
    # Not validated
    "gofile": StorageConfig(allowed=False),
    # Not validated
    "gcs": StorageConfig(allowed=False),
    # Not validated
    "gphotos": StorageConfig(allowed=False),
    # "hasher" refers to other rclone configs
    "hasher": StorageConfig(allowed=False),
    # Not validated
    "hdfs": StorageConfig(allowed=False),
    # Not validated
    "hidrive": StorageConfig(allowed=False),
    # Allow http
    "http": StorageConfig(
        allowed=True,
        options={
            "url": True,
            "headers": True,
            "no_slash": True,
            "no_head": True,
            "no_escape": True,
            "description": True,
        },
    ),
    # Not validated
    "iclouddrive": StorageConfig(allowed=False),
    # Not validated
    "imagekit": StorageConfig(allowed=False),
    # Not validated
    "internetarchive": StorageConfig(allowed=False),
    # Not validated
    "jottacloud": StorageConfig(allowed=False),
    # Not validated
    "koofr": StorageConfig(allowed=False),
    # Not validated
    "linkbox": StorageConfig(allowed=False),
    # "local" refers to the local filesystem
    "local": StorageConfig(allowed=False),
    # Not validated
    "mailru": StorageConfig(allowed=False),
    # Not validated
    "mega": StorageConfig(allowed=False),
    # "memory" refers to the local RAM
    "memory": StorageConfig(allowed=False),
    # Not validated
    "netstorage": StorageConfig(allowed=False),
    # Allow onedrive
    "onedrive": StorageConfig(
        allowed=True,
        options={
            "client_id": True,
            "client_secret": True,
            "token": True,
            "auth_url": True,
            "token_url": True,
            "client_credentials": True,
            "region": True,
            "upload_cutoff": True,
            "chunk_size": True,
            "drive_id": True,
            "drive_type": True,
            "root_folder_id": True,
            "access_scopes": True,
            "tenant": True,
            "disable_site_permission": True,
            "expose_onenote_files": True,
            "server_side_across_configs": True,
            "list_chunk": True,
            "no_versions": True,
            "hard_delete": True,
            "link_scope": True,
            "link_type": True,
            "link_password": True,
            "hash_type": True,
            "av_override": True,
            "delta": True,
            "metadata_permissions": True,
            "encoding": True,
            "description": True,
        },
    ),
    # Not validated
    "opendrive": StorageConfig(allowed=False),
    # Not validated
    "oos": StorageConfig(allowed=False),
    # Not validated
    "pcloud": StorageConfig(allowed=False),
    # Not validated
    "pikpak": StorageConfig(allowed=False),
    # Not validated
    "pixeldrain": StorageConfig(allowed=False),
    # Not validated
    "premiumizeme": StorageConfig(allowed=False),
    # Allow protondrive
    "protondrive": StorageConfig(
        allowed=True,
        options={
            "username": True,
            "password": True,
            "mailbox_password": True,
            "2fa": True,
            "client_uid": True,
            "client_access_token": True,
            "client_refresh_token": True,
            "client_salted_key_pass": True,
            "encoding": True,
            "original_file_size": True,
            "app_version": True,
            "replace_existing_draft": True,
            "enable_caching": True,
            "description": True,
        },
    ),
    # Not validated
    "putio": StorageConfig(allowed=False),
    # Not validated
    "qingstor": StorageConfig(allowed=False),
    # Not validated
    "quatrix": StorageConfig(allowed=False),
    # Allow s3
    "s3": StorageConfig(
        allowed=True,
        options={
            "provider": True,
            "env_auth": True,
            "access_key_id": True,
            "secret_access_key": True,
            "region": True,
            "endpoint": True,
            "location_constraint": True,
            "acl": True,
            "bucket_acl": True,
            "requester_pays": True,
            "server_side_encryption": True,
            "sse_customer_algorithm": True,
            "sse_kms_key_id": True,
            "sse_customer_key": True,
            "sse_customer_key_base64": True,
            "sse_customer_key_md5": True,
            "storage_class": True,
            "upload_cutoff": True,
            "chunk_size": True,
            "max_upload_parts": True,
            "copy_cutoff": True,
            "disable_checksum": True,
            # Path to a local file
            "shared_credentials_file": False,
            # Related to above option
            "profile": False,
            "session_token": True,
            "upload_concurrency": True,
            "force_path_style": True,
            "v2_auth": True,
            "use_dual_stack": True,
            "use_accelerate_endpoint": True,
            "use_arn_region": True,
            "leave_parts_on_error": True,
            "list_chunk": True,
            "list_version": True,
            "list_url_encode": True,
            "no_check_bucket": True,
            "no_head": True,
            "no_head_object": True,
            "encoding": True,
            "memory_pool_flush_time": True,
            "memory_pool_use_mmap": True,
            "disable_http2": True,
            "download_url": True,
            "directory_markers": True,
            "use_multipart_etag": True,
            "use_unsigned_payload": True,
            "use_presigned_request": True,
            "versions": True,
            "version_at": True,
            "version_deleted": True,
            "decompress": True,
            "might_gzip": True,
            "use_accept_encoding_gzip": True,
            "no_system_metadata": True,
            "sts_endpoint": True,
            "use_already_exists": True,
            "use_multipart_uploads": True,
            "use_x_id": True,
            "sign_accept_encoding": True,
            "directory_bucket": True,
            "sdk_log_mode": True,
            "ibm_api_key": True,
            "ibm_resource_instance_id": True,
            "description": True,
        },
    ),
    # Not validated
    "seafile": StorageConfig(allowed=False),
    # Allow sftp
    "sftp": StorageConfig(
        allowed=True,
        options={
            "host": True,
            "user": True,
            "port": True,
            "pass": True,
            "key_pem": True,
            # Path to a local file
            "key_file": False,
            # Related to above option
            "key_file_pass": False,
            "pubkey": True,
            # Path to a local file
            "pubkey_file": False,
            # Path to a local file
            "known_hosts_file": False,
            "key_use_agent": True,
            "use_insecure_cipher": True,
            "disable_hashcheck": True,
            "ask_password": True,
            "path_override": True,
            "set_modtime": True,
            "shell_type": True,
            "hashes": True,
            "md5sum_command": True,
            "sha1sum_command": True,
            "crc32sum_command": True,
            "sha256sum_command": True,
            "blake3sum_command": True,
            "xxh3sum_command": True,
            "xxh128sum_command": True,
            "skip_links": True,
            "subsystem": True,
            "server_command": True,
            "use_fstat": True,
            "disable_concurrent_reads": True,
            "disable_concurrent_writes": True,
            "idle_timeout": True,
            "chunk_size": True,
            "concurrency": True,
            "connections": True,
            "set_env": True,
            "ciphers": True,
            "key_exchange": True,
            "macs": True,
            "host_key_algorithms": True,
            # Arbitrary command to be executed
            "ssh": False,
            "socks_proxy": True,
            "http_proxy": True,
            "copy_is_hardlink": True,
            "description": True,
        },
    ),
    # Not validated
    "sharefile": StorageConfig(allowed=False),
    # Not validated
    "sia": StorageConfig(allowed=False),
    # Not validated
    "smb": StorageConfig(allowed=False),
    # Not validated
    "storj": StorageConfig(allowed=False),
    # Not validated
    "sugarsync": StorageConfig(allowed=False),
    # Not validated
    "swift": StorageConfig(allowed=False),
    # Not validated
    "tardigrade": StorageConfig(allowed=False),
    # Not validated
    "ulozto": StorageConfig(allowed=False),
    # "union" refers to other rclone configs
    "union": StorageConfig(allowed=False),
    # Not validated
    "uptobox": StorageConfig(allowed=False),
    # Allow webdav
    "webdav": StorageConfig(
        allowed=True,
        options={
            "url": True,
            "vendor": True,
            "user": True,
            "pass": True,
            "bearer_token": True,
            # Arbitrary command to be executed
            "bearer_token_command": False,
            "encoding": True,
            "headers": True,
            "pacer_min_sleep": True,
            "nextcloud_chunk_size": True,
            "owncloud_exclude_shares": True,
            "owncloud_exclude_mounts": True,
            "unix_socket": True,
            "auth_redirect": True,
            "description": True,
        },
    ),
    # Not validated
    "yandex": StorageConfig(allowed=False),
    # Not validated
    "zoho": StorageConfig(allowed=False),
}

BLOCKED_STORAGES: Final[set[str]] = set(key for key in STORAGE_CONFIG if not STORAGE_CONFIG[key].allowed)

BLOCKED_OPTIONS: Final[dict[str, set[str]]] = dict(
    (key, set(o for o in config.options if not config.options[o]))
    for key, config in STORAGE_CONFIG.items()
    if config.allowed and config.options
)
