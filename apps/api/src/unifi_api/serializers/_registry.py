"""Serializer registry: lookup helpers + auto-discovery + manifest validation."""

from __future__ import annotations

import importlib
import pkgutil
import sys
from typing import Any, Iterable

from unifi_api.serializers._base import (
    _RESOURCE_KIND_OVERRIDES,
    _RESOURCE_REGISTRY,
    _TOOL_KIND_OVERRIDES,
    _TOOL_REGISTRY,
    RenderKind,
    Serializer,
    _reset_registries_for_tests,
)


class SerializerRegistryError(Exception):
    """Raised when the registry is in an invalid state (e.g., missing serializer)."""


class SerializerRegistry:
    def serializer_for_tool(self, tool_name: str) -> Serializer:
        s = _TOOL_REGISTRY.get(tool_name)
        if s is None:
            raise SerializerRegistryError(f"no serializer registered for tool '{tool_name}'")
        return s

    def serializer_for_resource(self, product: str, resource: str) -> Serializer:
        s = _RESOURCE_REGISTRY.get((product, resource))
        if s is None:
            raise SerializerRegistryError(f"no serializer registered for resource ({product}, {resource})")
        return s

    def kind_for_tool(self, tool_name: str) -> RenderKind:
        if tool_name in _TOOL_KIND_OVERRIDES:
            return _TOOL_KIND_OVERRIDES[tool_name]
        return self.serializer_for_tool(tool_name).kind

    def kind_for_resource(self, product: str, resource: str) -> RenderKind:
        key = (product, resource)
        if key in _RESOURCE_KIND_OVERRIDES:
            return _RESOURCE_KIND_OVERRIDES[key]
        return self.serializer_for_resource(product, resource).kind

    def all_tools(self) -> Iterable[str]:
        return list(_TOOL_REGISTRY.keys())

    def all_resources(self) -> Iterable[tuple[str, str]]:
        return list(_RESOURCE_REGISTRY.keys())

    def render_hint_for_tool(self, tool_name: str) -> dict:
        s = self.serializer_for_tool(tool_name)
        kind = self.kind_for_tool(tool_name)
        return s._render_hint(kind)

    def render_hint_for_resource(self, product: str, resource: str) -> dict:
        s = self.serializer_for_resource(product, resource)
        kind = self.kind_for_resource(product, resource)
        return s._render_hint(kind)

    def validate_manifest(
        self,
        manifest_tool_names: set[str],
        type_registry: Any | None = None,
    ) -> None:
        """Every tool in the manifest must have a projection — either a
        serializer (mutation tools) or a Strawberry type (read tools, since
        Phase 6 close).
        """
        serializer_tools = set(_TOOL_REGISTRY.keys())
        type_tools: set[str] = set()
        if type_registry is not None:
            type_tools = set(type_registry.all_tools())
        missing = manifest_tool_names - serializer_tools - type_tools
        if missing:
            raise SerializerRegistryError(f"missing projection for {len(missing)} tools: {sorted(missing)[:5]}...")


_singleton: SerializerRegistry | None = None


def serializer_registry_singleton() -> SerializerRegistry:
    global _singleton
    if _singleton is None:
        _singleton = SerializerRegistry()
    return _singleton


def discover_serializers(
    manifest_tool_names: set[str],
    type_registry: Any | None = None,
) -> SerializerRegistry:
    """Walk the serializers package, import every submodule (decorators self-register),
    then validate against the manifest. Called once during lifespan startup.

    ``type_registry`` is consulted by ``validate_manifest`` so read tools whose
    projection is a Strawberry type (Phase 6 close) count as covered.
    """
    for product in ("network", "protect", "access"):
        try:
            product_pkg = importlib.import_module(f"unifi_api.serializers.{product}")
        except ModuleNotFoundError:
            continue
        for _, modname, ispkg in pkgutil.iter_modules(product_pkg.__path__):
            if ispkg or modname.startswith("_"):
                continue
            importlib.import_module(f"unifi_api.serializers.{product}.{modname}")
    reg = serializer_registry_singleton()
    reg.validate_manifest(manifest_tool_names, type_registry=type_registry)
    return reg


def _reset_registry_for_tests() -> None:
    """For test isolation — drops module-level registries AND evicts serializer
    submodules from sys.modules so the next discover_serializers re-imports
    them and re-runs the @register_serializer decorators. Without the eviction,
    importlib.import_module is a no-op for already-loaded modules and the
    registry stays empty after reset."""
    global _singleton
    _reset_registries_for_tests()
    _singleton = None
    for product in ("network", "protect", "access"):
        prefix = f"unifi_api.serializers.{product}"
        for modname in list(sys.modules.keys()):
            if modname == prefix or modname.startswith(prefix + "."):
                sys.modules.pop(modname, None)
