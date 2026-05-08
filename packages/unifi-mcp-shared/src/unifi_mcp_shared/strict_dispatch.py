"""StrictKwargFastMCP: transport-layer kwarg validation for FastMCP servers.

FastMCP's ``tools/call`` handler runs incoming ``arguments`` through pydantic
with ``extra="ignore"`` (the default), which silently drops unknown keys.
Result: callers passing typos or stale field names get ``success=True`` from
tools that didn't actually receive the param — the silent-drop class behind
issue #135 and similar.

This subclass overrides :meth:`call_tool` to diff incoming ``arguments`` keys
against the tool's declared input schema (loaded from ``tools_manifest.json``)
BEFORE pydantic sees them. Unknown keys raise ``ToolError`` with a structured
message naming the offending key(s) and the valid set so an LLM can self-correct.

Operates as composition (no FastMCP internals patched). Self-retires once
upstream lands ``extra="forbid"`` — the override becomes a no-op guard.
"""

from __future__ import annotations

import json
import logging
import pathlib
from typing import Any, Sequence

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ContentBlock

logger = logging.getLogger(__name__)


class StrictKwargFastMCP(FastMCP):
    """FastMCP subclass that rejects unknown top-level kwargs at dispatch time.

    Reads ``tools_manifest.json`` once at construction and caches the allowed
    top-level argument names per tool. Unknown keys at ``call_tool`` time
    raise :class:`mcp.server.fastmcp.exceptions.ToolError` with a structured,
    human-readable message.

    Note: only top-level kwargs are checked. Inner dict shapes (e.g. a
    ``policy_data`` blob) are the responsibility of the schema layer (#206).
    """

    def __init__(
        self,
        *args: Any,
        tools_manifest_path: pathlib.Path | str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._allowed_kwargs: dict[str, frozenset[str]] = {}
        if tools_manifest_path is not None:
            self._allowed_kwargs = _load_allowed_kwargs(pathlib.Path(tools_manifest_path))

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> Sequence[ContentBlock] | dict[str, Any]:
        """Dispatch a tool call after validating top-level kwargs.

        - Tools not present in the manifest cache (stale manifest, dynamically
          registered, or empty cache) pass through to FastMCP unchanged so
          its own "Unknown tool" path still works.
        - Tools present in the cache with unknown kwargs raise ``ToolError``.
        - All other cases delegate to ``super().call_tool``.
        """
        if name in self._allowed_kwargs:
            allowed = self._allowed_kwargs[name]
            unknown = set(arguments.keys()) - allowed
            if unknown:
                unknown_str = ", ".join(sorted(unknown))
                valid_str = ", ".join(sorted(allowed))
                raise ToolError(
                    f"Invalid params for '{name}': "
                    f"unknown arguments {{{unknown_str}}}. "
                    f"Valid arguments: [{valid_str}]."
                )
        return await super().call_tool(name, arguments)


def _load_allowed_kwargs(manifest_path: pathlib.Path) -> dict[str, frozenset[str]]:
    """Load tools_manifest.json and build a per-tool allowed-kwargs cache.

    Returns an empty dict (graceful fallback) if the file is missing or its
    structure is unexpected; logs a warning so operators can notice.
    """
    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning(
            "[strict_dispatch] tools_manifest.json not found at %s; "
            "kwarg validation disabled (every tool falls through to super)",
            manifest_path,
        )
        return {}
    except OSError as exc:
        logger.warning(
            "[strict_dispatch] failed to read tools_manifest.json at %s: %s; "
            "kwarg validation disabled",
            manifest_path,
            exc,
        )
        return {}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning(
            "[strict_dispatch] tools_manifest.json at %s is not valid JSON: %s; "
            "kwarg validation disabled",
            manifest_path,
            exc,
        )
        return {}

    tools = data.get("tools") if isinstance(data, dict) else None
    if not isinstance(tools, list):
        logger.warning(
            "[strict_dispatch] tools_manifest.json at %s missing 'tools' list; "
            "kwarg validation disabled",
            manifest_path,
        )
        return {}

    allowed: dict[str, frozenset[str]] = {}
    skipped: list[str] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = tool.get("name")
        if not isinstance(name, str):
            continue
        properties = (
            tool.get("schema", {}).get("input", {}).get("properties")
            if isinstance(tool.get("schema"), dict)
            else None
        )
        if not isinstance(properties, dict):
            skipped.append(name)
            # Tool with no declared input schema is treated as "no kwargs allowed".
            allowed[name] = frozenset()
            continue
        allowed[name] = frozenset(properties.keys())

    if skipped:
        logger.warning(
            "[strict_dispatch] %d tool(s) in manifest had no input schema; "
            "treated as zero-arg: %s",
            len(skipped),
            sorted(skipped),
        )

    logger.debug(
        "[strict_dispatch] loaded allowed-kwargs for %d tool(s) from %s",
        len(allowed),
        manifest_path,
    )
    return allowed
