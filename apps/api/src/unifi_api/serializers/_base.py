"""Serializer base + decorator. See decision-a63cb266 for ownership rationale."""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable


class RenderKind(str, Enum):
    LIST = "list"
    DETAIL = "detail"
    DIFF = "diff"
    TIMESERIES = "timeseries"
    EVENT_LOG = "event_log"
    EMPTY = "empty"
    STREAM = "stream"


class SerializerContractError(Exception):
    """Raised when manager-method return type doesn't match declared kind."""


class Serializer:
    """Subclass + override serialize() and declare kind. Optional richer
    metadata (primary_key, display_columns, sort_default) is per-serializer
    opt-in and surfaced in the catalog when present."""

    kind: RenderKind = RenderKind.EMPTY
    primary_key: str | None = None
    display_columns: list[str] | None = None
    sort_default: str | None = None

    # Per-tool / per-resource kind overrides — populated by the decorator.
    _tool_kinds: dict[str, RenderKind] = {}
    _resource_kinds: dict[tuple[str, str], RenderKind] = {}

    @staticmethod
    def serialize(obj) -> dict:
        raise NotImplementedError

    def _kind_for_tool(self, tool_name: str) -> RenderKind:
        return self._tool_kinds.get(tool_name, self.kind)

    def _kind_for_resource(self, product: str, resource: str) -> RenderKind:
        return self._resource_kinds.get((product, resource), self.kind)

    def _render_hint(self, kind: RenderKind) -> dict:
        hint: dict[str, Any] = {"kind": kind.value}
        if self.primary_key:
            hint["primary_key"] = self.primary_key
        if self.display_columns:
            hint["display_columns"] = list(self.display_columns)
        if self.sort_default:
            hint["sort_default"] = self.sort_default
        return hint

    def serialize_action(self, result, *, tool_name: str) -> dict:
        kind = self._kind_for_tool(tool_name)
        hint = self._render_hint(kind)
        if kind == RenderKind.LIST:
            if not isinstance(result, list):
                raise SerializerContractError(
                    f"tool '{tool_name}' declared kind=list but manager returned {type(result).__name__}"
                )
            return {"success": True, "data": [self.serialize(item) for item in result], "render_hint": hint}
        if kind == RenderKind.DETAIL:
            return {"success": True, "data": self.serialize(result), "render_hint": hint}
        if kind == RenderKind.EMPTY:
            return {"success": True, "render_hint": hint}
        if kind == RenderKind.DIFF:
            return {"success": True, "data": self.serialize(result), "render_hint": hint}
        if kind == RenderKind.STREAM:
            return {"success": True, "data": self.serialize(result), "render_hint": hint}
        if kind in (RenderKind.TIMESERIES, RenderKind.EVENT_LOG):
            if not isinstance(result, list):
                raise SerializerContractError(
                    f"tool '{tool_name}' declared kind={kind.value} but manager returned {type(result).__name__}"
                )
            return {"success": True, "data": [self.serialize(item) for item in result], "render_hint": hint}
        raise SerializerContractError(f"unknown kind {kind} for tool '{tool_name}'")


# Module-level registries populated by the decorator. Lookup helpers in _registry.py.
_TOOL_REGISTRY: dict[str, Serializer] = {}
_RESOURCE_REGISTRY: dict[tuple[str, str], Serializer] = {}
_TOOL_KIND_OVERRIDES: dict[str, RenderKind] = {}
_RESOURCE_KIND_OVERRIDES: dict[tuple[str, str], RenderKind] = {}


def register_serializer(
    *,
    tools: list[str] | dict[str, dict] | None = None,
    resources: list[tuple[str, str]] | list[tuple[tuple[str, str], dict]] | None = None,
) -> Callable[[type[Serializer]], type[Serializer]]:
    """Decorator: register a Serializer class under tool names and resource paths.

    `tools` accepts:
      - list[str]: bare tool names; serializer's class-level `kind` applies
      - dict[str, {"kind": RenderKind, ...}]: per-tool kind override
    Same shape for `resources` but keys are (product, resource_path) tuples.
    """

    def decorator(cls: type[Serializer]) -> type[Serializer]:
        instance = cls()  # singleton instance per registered serializer class
        if tools is not None:
            if isinstance(tools, dict):
                for name, spec in tools.items():
                    _TOOL_REGISTRY[name] = instance
                    if "kind" in spec:
                        _TOOL_KIND_OVERRIDES[name] = spec["kind"]
                        cls._tool_kinds = {**cls._tool_kinds, name: spec["kind"]}
            else:
                for name in tools:
                    _TOOL_REGISTRY[name] = instance
        if resources is not None:
            for entry in resources:
                if isinstance(entry, tuple) and len(entry) == 2 and isinstance(entry[0], tuple):
                    # ((product, resource), spec) form
                    key, spec = entry
                    _RESOURCE_REGISTRY[key] = instance
                    if isinstance(spec, dict) and "kind" in spec:
                        _RESOURCE_KIND_OVERRIDES[key] = spec["kind"]
                        cls._resource_kinds = {**cls._resource_kinds, key: spec["kind"]}
                else:
                    # (product, resource) bare-tuple form
                    _RESOURCE_REGISTRY[entry] = instance
        return cls

    return decorator


def _reset_registries_for_tests() -> None:
    _TOOL_REGISTRY.clear()
    _RESOURCE_REGISTRY.clear()
    _TOOL_KIND_OVERRIDES.clear()
    _RESOURCE_KIND_OVERRIDES.clear()
