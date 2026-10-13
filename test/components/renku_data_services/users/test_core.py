import pytest

from renku_data_services.errors import errors
from renku_data_services.users.core import fingerprint_ssh_public_key, validate_unsaved_ssh_key

# Fixed ed25519 test vector. Fingerprint must equal what OpenSSH prints:
#   ssh-keygen -l -f <file containing VALID_ED25519>
VALID_ED25519 = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPXhsNCQyI4HlAkaUIujCoGv3isiGoDR/MpS2yKlMfPY"
VALID_ED25519_FP = "SHA256:MkTiRU0eMct2d2W4oRdg5vMlg+38Wo57h53gs3IYVTc"


def test_validate_unsaved_ssh_key_canonicalizes_and_fingerprints():
    result = validate_unsaved_ssh_key(public_key=f"{VALID_ED25519} user@host", name=" laptop ")
    assert result.key_type == "ssh-ed25519"
    assert result.public_key.startswith("ssh-ed25519 ")
    assert "@host" not in result.public_key
    assert result.name == "laptop"
    assert result.fingerprint == VALID_ED25519_FP


def test_fingerprint_matches_openssh_definition():
    # SHA256 over the decoded key blob, base64 without padding, SHA256: prefixed.
    assert fingerprint_ssh_public_key(f"{VALID_ED25519} whatever@comment") == VALID_ED25519_FP


def test_validate_unsaved_ssh_key_rejects_garbage():
    with pytest.raises(errors.ValidationError):
        validate_unsaved_ssh_key(public_key="not a key", name=None)


def test_validate_unsaved_ssh_key_empty_name_is_none():
    assert validate_unsaved_ssh_key(public_key=VALID_ED25519, name="   ").name is None


def test_fingerprint_is_stable_across_comments():
    a = validate_unsaved_ssh_key(public_key=f"{VALID_ED25519} a@b", name=None)
    b = validate_unsaved_ssh_key(public_key=f"{VALID_ED25519} c@d", name=None)
    assert a.fingerprint == b.fingerprint
    assert a.public_key == b.public_key


def test_fingerprint_ssh_public_key_returns_none_for_garbage():
    assert fingerprint_ssh_public_key("not a key") is None
