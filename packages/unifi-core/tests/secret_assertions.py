"""Shared assertion for the credential-scrubbing regressions.

The oracle is written by hand rather than built from the production scrubber:
a test that reuses the enumeration under test cannot notice a form the
enumeration forgot. It carries the forms the emitters on these paths actually
produce — including the mixed ones, where a single value has some characters
escaped and others left literal.
"""

import codecs
import json
from urllib.parse import quote

# A credential holding a backslash, a quote, a newline and a non-ASCII
# character: no emitter renders all four the same way, which is what makes a
# whole-string enumeration look like it worked.
ESCAPED_SECRET = 'SENTINEL\\backslash"quote\nnewline-pä-e5c1'


def _encodings(secret: str) -> dict[str, str]:
    """Every rendering of ``secret`` a message on these paths can carry."""
    return {
        "literal": secret,
        "repr": repr(secret)[1:-1],
        "ascii": ascii(secret)[1:-1],
        # json.dumps escapes quotes and backslashes either way; ensure_ascii
        # decides only whether non-ASCII becomes \uXXXX or stays literal. Node,
        # Jackson and orjson all emit the second form on the wire.
        "json_ascii": json.dumps(secret)[1:-1],
        "json_unicode": json.dumps(secret, ensure_ascii=False)[1:-1],
        # aiounifi renders the raw body with repr(bytes) on its 429 path, which
        # escapes non-ASCII as UTF-8 byte escapes.
        "bytes_repr": repr(secret.encode())[2:-1],
        # A URL carries it percent-encoded, and ClientResponseError prints the
        # URL it failed on.
        "percent": quote(secret, safe=""),
    }


def assert_unrecoverable(text: str, secret: str) -> None:
    """The secret must not survive literally or in any form we can decode."""
    for name, form in _encodings(secret).items():
        assert form not in text, f"secret recoverable from its {name} form"
    # Best-effort, never swallowed: a partially scrubbed secret is exactly what
    # leaves a dangling escape behind, so a decode failure must not silently
    # turn into a pass. This leg only catches ASCII escapes — ``unicode_escape``
    # reads the UTF-8 bytes of a non-ASCII character as latin-1 — so the
    # enumerated forms above are what cover a non-ASCII secret.
    decoded = codecs.decode(text.encode("utf-8", "surrogatepass"), "unicode_escape", errors="replace")
    assert secret not in decoded
