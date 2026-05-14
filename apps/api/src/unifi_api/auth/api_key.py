"""API key generation, format validation, and argon2id hashing.

Format: unifi_<env>_<22-char-base32>
Env is "live" or "test". The 22-char body is base32-encoded random bytes.
The "prefix" exposed in audit logs is the first 15 chars (env + first 4 random).
"""

from __future__ import annotations

import re
import secrets
from base64 import b32encode
from dataclasses import dataclass
from enum import Enum

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

KEY_PATTERN = re.compile(r"^unifi_(live|test)_[A-Z2-7]{22}$")
KEY_PREFIX_LEN = 15
_HASHER = PasswordHasher()


class ApiKeyEnv(str, Enum):
    LIVE = "live"
    TEST = "test"


@dataclass(frozen=True)
class ApiKeyMaterial:
    plaintext: str
    prefix: str


def generate_key(env: ApiKeyEnv = ApiKeyEnv.LIVE) -> ApiKeyMaterial:
    body = b32encode(secrets.token_bytes(14)).decode("ascii").rstrip("=")[:22]
    plaintext = f"unifi_{env.value}_{body}"
    prefix = plaintext[:KEY_PREFIX_LEN]
    return ApiKeyMaterial(plaintext=plaintext, prefix=prefix)


def hash_key(plaintext: str) -> str:
    if not KEY_PATTERN.fullmatch(plaintext):
        raise ValueError("invalid key format")
    return _HASHER.hash(plaintext)


def verify_key(plaintext: str, digest: str) -> bool:
    if not KEY_PATTERN.fullmatch(plaintext):
        raise ValueError("invalid key format")
    try:
        return _HASHER.verify(digest, plaintext)
    except VerifyMismatchError:
        return False
