"""API key format and hashing tests."""

import re

import pytest
from unifi_api.auth.api_key import ApiKeyEnv, generate_key, hash_key, verify_key


def test_generate_key_has_correct_format() -> None:
    material = generate_key(env=ApiKeyEnv.LIVE)
    assert re.fullmatch(r"unifi_live_[A-Z2-7]{22}", material.plaintext)
    assert material.prefix == material.plaintext[:15]


def test_generate_key_test_env() -> None:
    material = generate_key(env=ApiKeyEnv.TEST)
    assert material.plaintext.startswith("unifi_test_")


def test_hash_and_verify() -> None:
    material = generate_key()
    digest = hash_key(material.plaintext)
    assert digest.startswith("$argon2id$")
    assert verify_key(material.plaintext, digest) is True
    assert verify_key("unifi_live_WRONGTOKENXXXXXXXXXXXX", digest) is False


def test_invalid_format_rejected() -> None:
    with pytest.raises(ValueError):
        verify_key("not_a_valid_key_format", "$argon2id$some-hash")
