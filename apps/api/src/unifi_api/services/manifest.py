"""Fail-closed lookup over the API-owned packaged action catalog."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib.resources import files
from typing import Any

CATALOG_RESOURCE = "action_catalog.json"
SUPPORTED_SCHEMA_VERSION = 1
PRODUCTS = frozenset({"network", "protect", "access"})
MUTATION_ACTIONS = frozenset({"create", "update", "delete"})


class ToolNotFound(Exception):
    """Raised when :meth:`ManifestRegistry.resolve` receives an unknown action."""


class CatalogLoadError(RuntimeError):
    """Raised when the packaged action catalog is absent or invalid."""


@dataclass(frozen=True)
class ToolEntry:
    """Validated safety metadata and Core manager binding for one API action."""

    name: str
    product: str
    category: str
    manager: str
    method: str
    permission_action: str = ""
    read_only_hint: bool | None = None
    input_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object"})

    @property
    def manager_attr(self) -> str:
        return self.manager

    @property
    def manager_method(self) -> str:
        return self.method


class ManifestRegistry:
    """Lookup table populated atomically from ``unifi_api/action_catalog.json``."""

    def __init__(self, entries: dict[str, ToolEntry]) -> None:
        self._entries = entries

    @classmethod
    def load(cls) -> ManifestRegistry:
        """Load and validate the API package's catalog without sibling app discovery."""
        try:
            raw = _read_catalog_resource()
        except (FileNotFoundError, ModuleNotFoundError, OSError) as exc:
            raise CatalogLoadError(f"cannot load packaged {CATALOG_RESOURCE}: {exc}") from exc
        return cls(_parse_catalog(raw))

    def has(self, name: str) -> bool:
        return name in self._entries

    def resolve(self, name: str) -> ToolEntry:
        entry = self._entries.get(name)
        if entry is None:
            raise ToolNotFound(name)
        return entry

    def all_categories_for_product(self, product: str) -> set[str]:
        return {entry.category for entry in self._entries.values() if entry.product == product}

    def all_tools(self) -> list[str]:
        return sorted(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


def _read_catalog_resource() -> str:
    return (files("unifi_api") / CATALOG_RESOURCE).read_text()


def _require_string(action: dict[str, Any], field: str, index: int) -> str:
    value = action.get(field)
    if not isinstance(value, str) or not value:
        raise CatalogLoadError(f"actions[{index}].{field} must be a non-empty string")
    return value


def _parse_catalog(raw: str) -> dict[str, ToolEntry]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CatalogLoadError(f"{CATALOG_RESOURCE} contains invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CatalogLoadError(f"{CATALOG_RESOURCE} top level must be an object")
    schema_version = data.get("schema_version")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise CatalogLoadError(
            f"unsupported schema_version {schema_version!r} in {CATALOG_RESOURCE}; expected {SUPPORTED_SCHEMA_VERSION}"
        )
    actions = data.get("actions")
    if not isinstance(actions, list):
        raise CatalogLoadError(f"{CATALOG_RESOURCE} actions must be an array")

    parsed: dict[str, ToolEntry] = {}
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise CatalogLoadError(f"actions[{index}] must be an object")
        name = _require_string(action, "name", index)
        if name in parsed:
            raise CatalogLoadError(f"duplicate action name {name!r} in {CATALOG_RESOURCE}")
        product = _require_string(action, "product", index)
        if product not in PRODUCTS:
            raise CatalogLoadError(f"actions[{index}].product must be one of {sorted(PRODUCTS)}")
        category = _require_string(action, "category", index)
        permission_action = _require_string(action, "permission_action", index)
        read_only_hint = action.get("read_only_hint")
        if not isinstance(read_only_hint, bool):
            raise CatalogLoadError(f"actions[{index}].read_only_hint must be boolean")
        if not (
            (permission_action == "read" and read_only_hint is True)
            or (permission_action in MUTATION_ACTIONS and read_only_hint is False)
        ):
            raise CatalogLoadError(
                f"actions[{index}] has conflicting safety metadata "
                f"(permission_action={permission_action!r}, read_only_hint={read_only_hint!r})"
            )
        manager_attr = _require_string(action, "manager_attr", index)
        manager_method = _require_string(action, "manager_method", index)
        input_schema = action.get("input_schema")
        if not isinstance(input_schema, dict):
            raise CatalogLoadError(f"actions[{index}].input_schema must be an object")
        if input_schema.get("type") != "object":
            raise CatalogLoadError(f"actions[{index}].input_schema.type must be 'object'")
        if not isinstance(input_schema.get("properties"), dict):
            raise CatalogLoadError(f"actions[{index}].input_schema.properties must be an object")
        if input_schema.get("additionalProperties") is not False:
            raise CatalogLoadError(f"actions[{index}].input_schema.additionalProperties must be false")
        parsed[name] = ToolEntry(
            name=name,
            product=product,
            category=category,
            permission_action=permission_action,
            read_only_hint=read_only_hint,
            manager=manager_attr,
            method=manager_method,
            input_schema=input_schema,
        )
    return parsed
