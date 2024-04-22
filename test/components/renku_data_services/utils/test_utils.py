from renku_data_services.utils.cryptography import decrypt_string, encrypt_string


def test_can_decrypt_correctly():
    data = "some data"
    password = b"some password"
    salt = "some salt"
    encrypted_data = encrypt_string(password=password, salt=salt, data=data)

    decrypted_data = decrypt_string(password=password, salt=salt, data=encrypted_data)

    assert decrypted_data == data
