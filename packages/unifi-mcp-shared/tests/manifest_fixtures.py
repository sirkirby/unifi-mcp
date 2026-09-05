"""Builders for tools_manifest.json fixtures shared by the dispatch tests."""

from __future__ import annotations

import json
import pathlib


def write_manifest(tmp_path: pathlib.Path, tools: list[dict]) -> pathlib.Path:
    """Write a tools_manifest.json with the given tool entries and return its path."""
    path = tmp_path / "tools_manifest.json"
    path.write_text(json.dumps({"count": len(tools), "tools": tools}), encoding="utf-8")
    return path


def make_tool(name: str, properties: dict[str, dict] | None, aliases: dict | list | None = None) -> dict:
    """Build a manifest tool entry. ``properties=None`` omits the input schema; *aliases* adds ``argument_aliases``."""
    entry: dict = {"name": name, "schema": {}}
    if properties is not None:
        entry["schema"] = {"input": {"type": "object", "properties": properties, "required": []}}
    if aliases is not None:
        entry["argument_aliases"] = aliases
    return entry
