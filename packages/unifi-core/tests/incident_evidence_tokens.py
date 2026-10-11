"""The size tests' oracles for an MCP tool result, read from the bytes a server sends.

MCP servers send a dict result as JSON indented by two spaces, non-ASCII text
unescaped. Both oracles read that serialization, not the view's estimator:

- :func:`bytes_as_sent` is its UTF-8 size.
- :func:`tokens_as_sent` is the most tokens a byte-level tokenizer can need
  for it: every byte of a string value is a token, since no token is shorter
  than a byte. Field names, numbers, literals and JSON's own punctuation and
  indentation read as words do: letters one token per four, digits one per
  three when in a name, every whitespace run, punctuation character and
  other digit one each.
"""

from __future__ import annotations

import math
import re
from typing import Any

import pydantic_core

# A string literal, and the colon that makes it a field name; a letter or
# digit run; a whitespace run or any other character.
_SENT_PARTS = re.compile(
    r'(?P<string>"(?:[^"\\]|\\.)*")(?P<colon>:?)|(?P<letters>[A-Za-z]+)|(?P<digits>[0-9]+)|\s+|.', re.DOTALL
)
_NAME_PARTS = re.compile(r"[A-Za-z]+|[0-9]+|[\s\S]")


def sent(payload: Any) -> bytes:
    """``{"success": true, "data": payload}`` as an MCP server sends it."""
    return pydantic_core.to_json({"success": True, "data": payload}, indent=2)


def bytes_as_sent(payload: Any) -> int:
    return len(sent(payload))


def _name(literal: str) -> int:
    total = 0
    for part in _NAME_PARTS.findall(literal):
        if part.isascii() and part.isalpha():
            total += math.ceil(len(part) / 4)
        elif part.isascii() and part.isdigit():
            total += math.ceil(len(part) / 3)
        else:
            total += len(part.encode())
    return total


def tokens_as_sent(payload: Any) -> int:
    """Most tokens ``{"success": true, "data": payload}`` can take as an MCP server sends it."""
    total = 0
    for part in _SENT_PARTS.finditer(sent(payload).decode()):
        if part["string"] is not None:
            literal = part["string"]
            total += 2 + _name(literal[1:-1]) + 1 if part["colon"] else len(literal.encode())
        elif part["letters"]:
            total += math.ceil(len(part["letters"]) / 4)
        elif part["digits"]:
            total += len(part["digits"])
        else:
            total += 1
    return total
