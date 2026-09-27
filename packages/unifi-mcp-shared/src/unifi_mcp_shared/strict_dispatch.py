"""StrictKwargFastMCP: transport-layer kwarg validation for FastMCP servers.

FastMCP's ``tools/call`` handler runs incoming ``arguments`` through pydantic
with ``extra="ignore"`` (the default), which silently drops unknown keys.
Result: callers passing typos or stale field names get ``success=True`` from
tools that didn't actually receive the param — a silent-drop class of bug.

This subclass overrides :meth:`call_tool` to diff incoming ``arguments`` keys
against the tool's declared input schema (loaded from ``tools_manifest.json``)
BEFORE pydantic sees them. Unknown keys raise ``ToolError`` with a structured
message naming the offending key(s) and the valid set so an LLM can self-correct.
When a rejected key is another spelling of this tool's MAC parameter, the message
also names the parameter to use — guidance only; the key itself stays invalid.

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

logger = logging.getLogger(__name__)

# Network tools take the subject MAC as ``mac_address``. Older callers may still
# send ``client_mac``, ``device_mac``, or ``mac``; reject them and name the current
# parameter in the error. This remains guidance, not an alias.
#
# ``ap_mac`` is deliberately absent. It names a different thing — the access point
# to scan from, not the subject of the call — so telling a caller holding a client
# MAC to resend it as ``ap_mac`` would turn a rejected call into a wrong answer,
# which is what this module exists to prevent.
_MAC_ARGUMENT_SPELLINGS = frozenset({"mac", "mac_address", "client_mac", "device_mac"})


def _mac_parameter_hint(tool_name: str, unknown: set[str], allowed: frozenset[str], arguments: dict[str, Any]) -> str:
    """Name this tool's MAC parameter when a rejected key is another spelling of it.

    Empty string when no rejected key is a MAC spelling, when the tool takes no MAC
    parameter or more than one (then there is nothing to point at), or when the
    caller already sent the right one — repeating it back invites a retry that
    changes nothing.
    """
    if not unknown & _MAC_ARGUMENT_SPELLINGS:
        return ""
    canonical = sorted(allowed & _MAC_ARGUMENT_SPELLINGS)
    if len(canonical) != 1 or canonical[0] in arguments:
        return ""
    return " '%s' takes the MAC address as '%s'." % (tool_name, canonical[0])


class StrictKwargFastMCP(MCPServer):
    """FastMCP subclass that rejects unknown top-level kwargs at dispatch time.

    Reads ``tools_manifest.json`` once at construction and caches the allowed
    top-level argument names per tool. Unknown keys at ``call_tool`` time
    raise :class:`mcp.server.mcpserver.exceptions.ToolError` with a structured,
    human-readable message.

    Note: only top-level kwargs are checked. Inner dict shapes (e.g. a
    ``policy_data`` blob) are the responsibility of the schema layer.
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
        context: Context | None = None,
    ) -> Any:
        """Dispatch a tool call after validating top-level kwargs.

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
        if name in self._allowed_kwargs:
            allowed = self._allowed_kwargs[name]
            unknown = set(arguments.keys()) - allowed
            if unknown:
                unknown_str = ", ".join(sorted(unknown))
                valid_str = ", ".join(sorted(allowed))
                hint = _mac_parameter_hint(name, unknown, allowed, arguments)
                raise ToolError(
                    f"Invalid params for '{name}': unknown arguments {{{unknown_str}}}. "
                    f"Valid arguments: [{valid_str}].{hint}"
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
            "[strict_dispatch] failed to read tools_manifest.json at %s: %s; kwarg validation disabled",
            manifest_path,
            exc,
        )
        return {}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning(
            "[strict_dispatch] tools_manifest.json at %s is not valid JSON: %s; kwarg validation disabled",
            manifest_path,
            exc,
        )
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
        properties = (
            tool.get("schema", {}).get("input", {}).get("properties") if isinstance(tool.get("schema"), dict) else None
        )
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
