"""The size tests' token estimate of an MCP tool result.

MCP servers send a dict result as JSON indented by two spaces. Tokens are
estimated conservatively: every whitespace run and punctuation character is
a token, letters count one token per four and digits one per three.
"""

from __future__ import annotations

import math
import re
from typing import Any

import pydantic_core

_TOKEN_PARTS = re.compile(r"[A-Za-z]+|[0-9]+|\s+|[^\sA-Za-z0-9]")


def tokens_as_sent(payload: Any) -> int:
    """Estimated tokens of ``{"success": true, "data": payload}`` as an MCP server sends it."""
    text = pydantic_core.to_json({"success": True, "data": payload}, indent=2).decode()
    total = 0
    for part in _TOKEN_PARTS.findall(text):
        if part[0].isalpha():
            total += math.ceil(len(part) / 4)
        elif part[0].isdigit():
            total += math.ceil(len(part) / 3)
        else:
            total += 1
    return total
