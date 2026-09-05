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
from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from unifi_core.redaction import redaction_marker_paths

from unifi_mcp_shared.argument_aliases import ArgumentAliasMixin, argument_aliases_from_manifest

logger = logging.getLogger(__name__)


class StrictKwargFastMCP(ArgumentAliasMixin, MCPServer):
    """FastMCP subclass that rejects unknown top-level kwargs at dispatch time.

    Reads ``tools_manifest.json`` once at construction and caches the allowed
    top-level argument names per tool. Unknown keys at ``call_tool`` time
    raise :class:`mcp.server.mcpserver.exceptions.ToolError` with a structured,
    human-readable message.

    Declared argument aliases (:mod:`unifi_mcp_shared.argument_aliases`) are
    rewritten to their canonical names first, so an accepted alias is never
    reported as unknown. The alias state lives in a separate mixin because this
    guard retires when FastMCP forbids extra kwargs and the aliases do not.

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
            path = pathlib.Path(tools_manifest_path)
            manifest = _read_manifest(path)
            self._allowed_kwargs = _allowed_kwargs_from_manifest(manifest, path)
            self._argument_aliases = argument_aliases_from_manifest(manifest)

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Context | None = None,
    ) -> Any:
        """Dispatch a tool call after validating top-level kwargs.

        - Declared aliases are rewritten to canonical names before anything
          else looks at the keys (``ArgumentAliasMixin.apply_argument_aliases``).
        - Tools not present in the manifest cache (stale manifest, dynamically
          registered, or empty cache) pass through to FastMCP unchanged so
          its own "Unknown tool" path still works.
        - Tools present in the cache with unknown kwargs raise ``ToolError``.
        - Any argument carrying the redaction marker at a sensitive key raises
          ``ToolError`` (write-back guard, see below).
        - All other cases delegate to ``super().call_tool``.

        Write-back guard: redacted responses surface secrets as the redaction
        marker. An agent that echoes such a value back into a mutation would
        otherwise persist the literal marker as the real secret. Rejecting it
        once here covers every tool — including ``unifi_execute``/``unifi_batch``,
        which re-enter ``call_tool`` for their inner dispatch — so individual
        mutation tools need no per-field check. Mirrors the API-side guard in
        ``unifi_api.services.actions.dispatch_action``.
        """
        arguments = self.apply_argument_aliases(name, arguments)
        if name in self._allowed_kwargs:
            allowed = self._allowed_kwargs[name]
            unknown = set(arguments.keys()) - allowed
            if unknown:
                unknown_str = ", ".join(sorted(unknown))
                valid_str = ", ".join(sorted(allowed))
                raise ToolError(
                    f"Invalid params for '{name}': unknown arguments {{{unknown_str}}}. Valid arguments: [{valid_str}]."
                )
        marker_paths = redaction_marker_paths(arguments)
        if marker_paths:
            field = marker_paths[0]
            raise ToolError(
                f"Invalid params for '{name}': {field} is the redaction marker, not a real value. "
                f"Omit {field} to keep the current value."
            )
        return await super().call_tool(name, arguments, context=context)


def _load_allowed_kwargs(manifest_path: pathlib.Path) -> dict[str, frozenset[str]]:
    """Load tools_manifest.json and build a per-tool allowed-kwargs cache.

    Returns an empty dict (graceful fallback) if the file is missing or its
    structure is unexpected; logs a warning so operators can notice.
    """
    return _allowed_kwargs_from_manifest(_read_manifest(manifest_path), manifest_path)


def _read_manifest(manifest_path: pathlib.Path) -> Any:
    """Parse tools_manifest.json once; ``None`` (with a warning) when unreadable or invalid."""
    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning(
            "[strict_dispatch] tools_manifest.json not found at %s; "
            "kwarg validation disabled (every tool falls through to super)",
            manifest_path,
        )
        return None
    except OSError as exc:
        logger.warning(
            "[strict_dispatch] failed to read tools_manifest.json at %s: %s; kwarg validation disabled",
            manifest_path,
            exc,
        )
        return None

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning(
            "[strict_dispatch] tools_manifest.json at %s is not valid JSON: %s; kwarg validation disabled",
            manifest_path,
            exc,
        )
        return None


def _allowed_kwargs_from_manifest(data: Any, manifest_path: pathlib.Path) -> dict[str, frozenset[str]]:
    """Build the per-tool allowed-kwargs cache from a parsed manifest (``None`` -> empty)."""
    if data is None:
        return {}
    tools = data.get("tools") if isinstance(data, dict) else None
    if not isinstance(tools, list):
        logger.warning(
            "[strict_dispatch] tools_manifest.json at %s missing 'tools' list; kwarg validation disabled",
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
        schema = tool.get("schema")
        input_schema = schema.get("input") if isinstance(schema, dict) else None
        properties = input_schema.get("properties") if isinstance(input_schema, dict) else None
        if not isinstance(properties, dict):
            skipped.append(name)
            # Tool with no declared input schema is treated as "no kwargs allowed".
            allowed[name] = frozenset()
            continue
        allowed[name] = frozenset(properties.keys())

    if skipped:
        logger.warning(
            "[strict_dispatch] %d tool(s) in manifest had no input schema; treated as zero-arg: %s",
            len(skipped),
            sorted(skipped),
        )

    logger.debug(
        "[strict_dispatch] loaded allowed-kwargs for %d tool(s) from %s",
        len(allowed),
        manifest_path,
    )
    return allowed
