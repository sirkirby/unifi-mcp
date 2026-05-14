"""AES-GCM column encryption tests."""

import os

import pytest
from unifi_api.db.crypto import ColumnCipher, derive_key


def test_encrypt_decrypt_roundtrip() -> None:
    cipher = ColumnCipher(key=os.urandom(32))
    plaintext = b'{"username":"admin","password":"hunter2"}'
    ciphertext = cipher.encrypt(plaintext)
    assert ciphertext != plaintext
    assert cipher.decrypt(ciphertext) == plaintext


def test_wrong_key_fails() -> None:
    cipher_a = ColumnCipher(key=os.urandom(32))
    cipher_b = ColumnCipher(key=os.urandom(32))
    ct = cipher_a.encrypt(b"secret")
    with pytest.raises(Exception):
        cipher_b.decrypt(ct)


def test_each_encrypt_uses_fresh_nonce() -> None:
    cipher = ColumnCipher(key=os.urandom(32))
    a = cipher.encrypt(b"same input")
    b = cipher.encrypt(b"same input")
    assert a != b  # different nonces ⇒ different ciphertexts


def test_derive_key_from_short_passphrase() -> None:
    k = derive_key("a-shortish-passphrase")
    assert isinstance(k, bytes)
    assert len(k) == 32


def test_derive_key_accepts_raw_32_bytes() -> None:
    raw = os.urandom(32).hex()
    k = derive_key(raw)
    assert len(k) == 32
