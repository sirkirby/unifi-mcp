"""Shared build-time tool manifest generator.

Each UniFi MCP server ships a thin wrapper script (``scripts/generate_tool_manifest.py``)
that calls :func:`generate_and_write` with its package identity. This module owns the
identical machinery the wrappers used to duplicate verbatim: forcing eager mode,
patching the decorator, registering meta-tools, scanning for tool names, and writing
the JSON output.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import re
import sys
import traceback
from pathlib import Path
from typing import Any

from unifi_core.manifest_helpers import get_tool_annotations

from unifi_mcp_shared.meta_tools import register_load_tools, register_meta_tools
from unifi_mcp_shared.tool_loader import auto_load_tools


class _ManifestLazyLoader:
    async def load_tool(self, tool_name: str) -> bool:
        return False


def _build_module_map(
    *,
    project_root: Path,
    package: str,
    tool_prefix: str,
    logger: logging.Logger,
) -> dict[str, str]:
    tool_map: dict[str, str] = {}
    tools_dir = project_root / "src" / package / "tools"

    if not tools_dir.exists():
        logger.warning("Tools directory not found at %s", tools_dir)
        return tool_map

    pattern = re.compile(rf'name\s*=\s*["\']({re.escape(tool_prefix)}[a-z_]+)["\']')

    for tool_file in tools_dir.glob("*.py"):
        if tool_file.name.startswith("_"):
            continue

        module_name = f"{package}.tools.{tool_file.stem}"

        try:
            content = tool_file.read_text()
            for tool_name in pattern.findall(content):
                tool_map[tool_name] = module_name
        except Exception as e:
            logger.warning("Error scanning %s: %s", tool_file, e)

    logger.info("   Built module map with %s tool->module mappings", len(tool_map))
    return tool_map


def _generate_manifest(
    *,
    project_root: Path,
    package: str,
    tool_prefix: str,
    meta_prefix: str,
    server_label: str,
    fallback_label: str,
    logger: logging.Logger,
) -> dict[str, Any]:
    logger.info("Generating tool manifest with full schemas...")

    tool_index_mod = importlib.import_module(f"{package}.tool_index")
    tool_registry = tool_index_mod.TOOL_REGISTRY

    logger.info("   Setting up permissioned tool decorator...")
    importlib.import_module(f"{package}.main")

    logger.info("   Registering shared meta-tool schemas...")
    categories_mod = importlib.import_module(f"{package}.categories")
    jobs_mod = importlib.import_module(f"{package}.jobs")
    runtime_mod = importlib.import_module(f"{package}.runtime")

    server = runtime_mod.server
    tool_decorator = getattr(server, "_original_tool", server.tool)

    register_meta_tools(
        server=server,
        tool_decorator=tool_decorator,
        tool_index_handler=tool_index_mod.tool_index_handler,
        start_async_tool=jobs_mod.start_async_tool,
        get_job_status=jobs_mod.get_job_status,
        register_tool=tool_index_mod.register_tool,
        prefix=meta_prefix,
        server_label=server_label,
    )
    register_load_tools(
        server=server,
        tool_decorator=tool_decorator,
        lazy_loader=_ManifestLazyLoader(),
        register_tool=tool_index_mod.register_tool,
        tool_module_map=categories_mod.TOOL_MODULE_MAP,
        prefix=meta_prefix,
        server_label=server_label,
    )

    logger.info("   Loading all tools in eager mode to extract schemas...")
    try:
        auto_load_tools(base_package=f"{package}.tools")
        logger.info("   Loaded %s tools into registry", len(tool_registry))
    except Exception as e:
        logger.error("   Failed to load tools: %s", e)
        traceback.print_exc()

        logger.warning("   Falling back to minimal manifest from TOOL_MODULE_MAP")
        tools = [
            {
                "name": tool_name,
                "description": f"{fallback_label} tool: {tool_name}",
                "schema": {"input": {"type": "object", "properties": {}}},
            }
            for tool_name in sorted(categories_mod.TOOL_MODULE_MAP.keys())
        ]
        return {
            "tools": tools,
            "count": len(tools),
            "generated_by": "scripts/generate_tool_manifest.py",
            "note": "Fallback manifest with minimal schemas due to loading error.",
            "error": str(e),
        }

    annotations_map = get_tool_annotations(server)
    if annotations_map:
        logger.info("   Extracted annotations for %s tools", len(annotations_map))
    else:
        logger.warning("   No tool annotations found in FastMCP registry")

    tools: list[dict[str, Any]] = []
    for tool_name in sorted(tool_registry.keys()):
        meta = tool_registry[tool_name]

        tool_data: dict[str, Any] = {
            "name": meta.name,
            "description": meta.description,
            "schema": {"input": meta.input_schema},
        }
        if meta.title:
            tool_data["title"] = meta.title
        if meta.output_schema:
            tool_data["schema"]["output"] = meta.output_schema
        if tool_name in annotations_map:
            tool_data["annotations"] = annotations_map[tool_name]
        if meta.permission_category:
            tool_data["permission_category"] = meta.permission_category
        if meta.permission_action:
            tool_data["permission_action"] = meta.permission_action

        tools.append(tool_data)

    module_map = _build_module_map(
        project_root=project_root,
        package=package,
        tool_prefix=tool_prefix,
        logger=logger,
    )

    manifest = {
        "tools": tools,
        "module_map": module_map,
        "count": len(tools),
        "generated_by": "scripts/generate_tool_manifest.py",
        "note": "Auto-generated with full schemas from tool decorators. Do not edit manually.",
    }

    logger.info("   Generated manifest with %s tools and full schemas", len(tools))
    if tools:
        sample_tool = tools[0]
        logger.info("   Sample tool: %s", sample_tool["name"])
        logger.info("      Properties: %s", list(sample_tool["schema"]["input"].get("properties", {}).keys()))

    return manifest


def generate_and_write(
    *,
    project_root: Path,
    package: str,
    tool_prefix: str,
    meta_prefix: str,
    server_label: str,
    fallback_label: str | None = None,
) -> int:
    """Generate a tool manifest for the given app package and write it to disk.

    Args:
        project_root: App root (parent of ``src/<package>/``); typically
            ``Path(__file__).parent.parent`` in the wrapper script.
        package: Importable package name (e.g. ``"unifi_network_mcp"``).
        tool_prefix: Tool name prefix scanned in tool source files (e.g. ``"unifi_"``).
        meta_prefix: Prefix passed to meta-tool registration (e.g. ``"unifi"``).
        server_label: Human-readable server label (e.g. ``"UniFi Network"``).
        fallback_label: Label used in the minimal fallback manifest descriptor.
            Defaults to ``server_label`` if not supplied.

    Returns:
        Process exit code: 0 on success, 1 on unhandled failure.
    """
    sys.path.insert(0, str(project_root / "src"))
    os.environ["UNIFI_TOOL_REGISTRATION_MODE"] = "eager"

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger = logging.getLogger(__name__)

    try:
        manifest = _generate_manifest(
            project_root=project_root,
            package=package,
            tool_prefix=tool_prefix,
            meta_prefix=meta_prefix,
            server_label=server_label,
            fallback_label=fallback_label or server_label,
            logger=logger,
        )

        output_path = project_root / "src" / package / "tools_manifest.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            json.dump(manifest, f, indent=2, sort_keys=True)

        logger.info("   Wrote manifest to %s", output_path)
        logger.info("   Tool manifest generation complete!")
        return 0
    except Exception as e:
        logger.error("   Failed to generate manifest: %s", e)
        traceback.print_exc()
        return 1
