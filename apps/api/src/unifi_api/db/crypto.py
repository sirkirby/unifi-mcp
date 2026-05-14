"""AES-256-GCM column-level encryption.

The encryption key is supplied via `UNIFI_API_DB_KEY` and consumed via
`derive_key()`, which accepts either a 32-byte raw key (hex or base64
encoded) or any shorter string (derived via HKDF-SHA256).

Wire format per encrypted column: nonce (12 bytes) || ciphertext || tag.
The cryptography AESGCM helper packs ciphertext+tag together; we prepend
a fresh nonce per encrypt call.
"""

from __future__ import annotations

import base64
import os
from binascii import unhexlify

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_NONCE_SIZE = 12
_KEY_SIZE = 32


def derive_key(material: str) -> bytes:
    """Return a 32-byte key.

    If `material` is a 64-char hex or base64 string decodable to 32 bytes,
    use it directly. Otherwise apply HKDF-SHA256 with a fixed info label
    so derivations are deterministic for a given passphrase.
    """
    if len(material) == 64:
        try:
            decoded = unhexlify(material)
            if len(decoded) == _KEY_SIZE:
                return decoded
        except Exception:
            pass
    try:
        decoded = base64.b64decode(material, validate=True)
        if len(decoded) == _KEY_SIZE:
            return decoded
    except Exception:
        pass
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=_KEY_SIZE,
        salt=None,
        info=b"unifi-api column-cipher v1",
    )
    return hkdf.derive(material.encode("utf-8"))


class ColumnCipher:
    """Symmetric AES-256-GCM cipher for a single column's values."""

    def __init__(self, key: bytes) -> None:
        if len(key) != _KEY_SIZE:
            raise ValueError(f"key must be {_KEY_SIZE} bytes, got {len(key)}")
        self._aead = AESGCM(key)

    def encrypt(self, plaintext: bytes, *, associated_data: bytes | None = None) -> bytes:
        nonce = os.urandom(_NONCE_SIZE)
        ct = self._aead.encrypt(nonce, plaintext, associated_data)
        return nonce + ct

    def decrypt(self, blob: bytes, *, associated_data: bytes | None = None) -> bytes:
        nonce, ct = blob[:_NONCE_SIZE], blob[_NONCE_SIZE:]
        return self._aead.decrypt(nonce, ct, associated_data)
