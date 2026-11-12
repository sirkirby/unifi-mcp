"""Synthetic secret sentinels shared by Site Manager egress regressions."""

import base64
import hashlib

KEY = "synthetic-cloud-key-DO-NOT-DISCLOSE-42"


def assert_no_cloud_secret(value, *, key=KEY, ciphertexts=()):
    text = str(value)
    sentinels = [
        key,
        key[:8],
        key[-8:],
        key.encode().hex(),
        base64.b64encode(key.encode()).decode(),
        hashlib.sha256(key.encode()).hexdigest(),
        "**********",
        "***REDACTED***",
    ]
    for blob in ciphertexts:
        sentinels.extend(
            (blob.hex(), base64.b64encode(blob).decode(), base64.urlsafe_b64encode(blob).decode(), repr(blob))
        )
    for sentinel in sentinels:
        assert sentinel not in text, "A cloud credential representation escaped its boundary"
