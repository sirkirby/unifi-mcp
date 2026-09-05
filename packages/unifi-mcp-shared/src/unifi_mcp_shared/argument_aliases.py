"""Argument aliases: accept deprecated parameter spellings at the MCP dispatch boundary.

Tools across the Network server name the same thing three ways: ``mac_address``,
``device_mac``, ``client_mac`` (and ``mac`` once). An agent that learned one
spelling on one tool gets ``unknown arguments`` from the next. Renaming the
parameters would change every tool's schema, the API action catalog and ~20
REST translators, so instead each tool declares which other spellings it
accepts and the server rewrites them to the canonical name before the strict
kwarg guard and pydantic see the call.

Source of truth is the generated ``tools_manifest.json`` (top-level
``argument_aliases`` per tool, ``{alias: canonical}``), written by the manifest
generator from what the ``permissioned_tool`` decorator recorded. The rewrite
therefore covers every registration mode and the ``unifi_execute`` /
``unifi_batch`` re-entry, which all pass through ``call_tool``. Schemas are
unchanged: aliases never appear in ``inputSchema`` or the API catalog.

The alias state and rewrite live in :class:`ArgumentAliasMixin`, separate from
:class:`~unifi_mcp_shared.strict_dispatch.StrictKwargFastMCP`, because that
guard is documented to retire once FastMCP forbids extra kwargs; whatever
``call_tool`` remains keeps calling :meth:`ArgumentAliasMixin.apply_argument_aliases`
first.
"""

from __future__ import annotations

import json
import logging
import pathlib
from typing import Any, Mapping

from mcp.server.mcpserver.exceptions import ToolError
from unifi_core.redaction import is_sensitive_key

logger = logging.getLogger(__name__)

__all__ = [
    "MAC_SPELLINGS",
    "ArgumentAliasMixin",
    "append_argument_alias_note",
    "argument_alias_note",
    "argument_aliases_from_manifest",
    "load_argument_aliases",
    "mac_aliases",
    "validate_argument_aliases",
]

#: Every spelling a MAC-identity parameter has been given, canonical first.
MAC_SPELLINGS: tuple[str, ...] = ("mac_address", "device_mac", "client_mac", "mac")


def mac_aliases(canonical: str) -> dict[str, str]:
    """Map every MAC spelling other than *canonical* to *canonical*.

    ``canonical`` need not be one of :data:`MAC_SPELLINGS`: a tool whose
    parameter is ``ap_mac`` or ``gateway_mac`` accepts all four.
    """
    return {spelling: canonical for spelling in MAC_SPELLINGS if spelling != canonical}


def validate_argument_aliases(
    tool_name: str,
    aliases: Any,
    properties: Mapping[str, Any],
) -> dict[str, str]:
    """Return *aliases* as a plain dict, or raise ``ValueError`` naming the defect.

    Rules: both sides are strings, an alias is not itself a declared parameter,
    the canonical name is one, ``confirm`` (the mutation arming switch) is never
    a target, and a sensitive-looking alias may only point at a sensitive
    canonical (otherwise a secret handed in under the alias would escape
    redaction under the canonical name).
    """
    if not isinstance(aliases, dict):
        raise ValueError(
            f"{tool_name}: argument_aliases must be a dict of alias -> canonical, got {type(aliases).__name__}"
        )
    validated: dict[str, str] = {}
    for alias, canonical in aliases.items():
        if not isinstance(alias, str) or not isinstance(canonical, str):
            raise ValueError(f"{tool_name}: argument_aliases entries must be strings")
        if alias in properties:
            raise ValueError(f"{tool_name}: alias '{alias}' collides with a declared parameter")
        if canonical not in properties:
            raise ValueError(f"{tool_name}: alias '{alias}' targets '{canonical}', which is not a declared parameter")
        if canonical == "confirm":
            raise ValueError(f"{tool_name}: alias '{alias}' may not target the confirmation parameter")
        if is_sensitive_key(alias) and not is_sensitive_key(canonical):
            raise ValueError(
                f"{tool_name}: sensitive alias '{alias}' may not target non-sensitive parameter '{canonical}'"
            )
        validated[alias] = canonical
    return validated


def _group_by_canonical(aliases: Mapping[str, str], *, only: Any = None) -> dict[str, list[str]]:
    """Invert ``{alias: canonical}`` to ``{canonical: [aliases]}``, keeping only aliases in *only*."""
    grouped: dict[str, list[str]] = {}
    for alias, canonical in aliases.items():
        if only is None or alias in only:
            grouped.setdefault(canonical, []).append(alias)
    return grouped


def argument_alias_note(aliases: Mapping[str, str]) -> str:
    """The sentence appended to a tool description listing its aliases."""
    parts = [
        f"{', '.join(names)} {'are' if len(names) > 1 else 'is'} accepted for {canonical} "
        f"(deprecated spelling{'s' if len(names) > 1 else ''}; prefer {canonical})"
        for canonical, names in _group_by_canonical(aliases).items()
    ]
    return f"Argument aliases: {'; '.join(parts)}."


def append_argument_alias_note(description: str, aliases: Mapping[str, str]) -> str:
    """Append :func:`argument_alias_note` after a sentence break so the first sentence stays intact."""
    base = description.rstrip()
    if base and not base.endswith((".", "!", "?")):
        base += "."
    return f"{base} {argument_alias_note(aliases)}".strip()


def _input_properties(tool: Mapping[str, Any]) -> dict[str, Any]:
    """The declared input properties of a manifest entry, ``{}`` for any malformed shape."""
    schema = tool.get("schema")
    input_schema = schema.get("input") if isinstance(schema, dict) else None
    properties = input_schema.get("properties") if isinstance(input_schema, dict) else None
    return properties if isinstance(properties, dict) else {}


def argument_aliases_from_manifest(manifest: Any) -> dict[str, dict[str, str]]:
    """Read per-tool aliases from a parsed ``tools_manifest.json``.

    Entries that fail :func:`validate_argument_aliases` are dropped with a
    warning rather than failing startup: a bad alias costs one spelling, not
    the server. Anything that is not a manifest yields an empty map.
    """
    tools = manifest.get("tools") if isinstance(manifest, dict) else None
    if not isinstance(tools, list):
        return {}
    aliases: dict[str, dict[str, str]] = {}
    for tool in tools:
        if not isinstance(tool, dict) or "argument_aliases" not in tool:
            continue
        name = tool.get("name")
        if not isinstance(name, str):
            continue
        try:
            validated = validate_argument_aliases(name, tool["argument_aliases"], _input_properties(tool))
        except ValueError as exc:
            logger.warning("[argument_aliases] dropping argument_aliases for %s: %s", name, exc)
            continue
        if validated:
            aliases[name] = validated
    return aliases


def load_argument_aliases(manifest_path: pathlib.Path) -> dict[str, dict[str, str]]:
    """:func:`argument_aliases_from_manifest` over a file; unreadable or invalid yields an empty map."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("[argument_aliases] cannot read %s (%s); aliases disabled", manifest_path, type(exc).__name__)
        return {}
    return argument_aliases_from_manifest(manifest)


class ArgumentAliasMixin:
    """Hold per-tool aliases and rewrite them in a server's ``call_tool``.

    Mix in ahead of ``MCPServer``, set ``_argument_aliases`` (see
    :func:`argument_aliases_from_manifest`) and call
    :meth:`apply_argument_aliases` before anything else reads the argument keys.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._argument_aliases: dict[str, dict[str, str]] = {}

    def apply_argument_aliases(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Return *arguments* with aliases renamed, or the same object when none apply.

        Passing an alias together with its canonical name, or two aliases of
        the same name, raises ``ToolError``: silently picking one would hide
        which value the tool acted on.
        """
        aliases = self._argument_aliases.get(name)
        if not aliases or aliases.keys().isdisjoint(arguments):
            return arguments
        rewritten = dict(arguments)
        for canonical, supplied in _group_by_canonical(aliases, only=arguments).items():
            if canonical in arguments or len(supplied) > 1:
                names = sorted(supplied + ([canonical] if canonical in arguments else []))
                raise ToolError(
                    f"Invalid params for '{name}': {', '.join(names)} name the same argument; pass only {canonical}."
                )
            rewritten[canonical] = rewritten.pop(supplied[0])
        return rewritten
