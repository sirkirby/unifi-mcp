#!/usr/bin/env python3
"""Generate static tool manifest at build time.

This script imports all tool modules in eager mode to extract their metadata
and writes a static JSON manifest. This allows lazy loading to provide full
tool schemas without runtime imports.

Usage:
    python scripts/generate_tool_manifest.py

Output:
    src/unifi_access_mcp/tools_manifest.json - Static tool metadata with FULL schemas for all tools
                                                Includes module_map for fallback lazy loading
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

from unifi_mcp_shared.manifest_helpers import get_tool_annotations

# Add src to path so we can import modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# Force eager mode for manifest generation
os.environ["UNIFI_TOOL_REGISTRATION_MODE"] = "eager"

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def build_module_map() -> dict[str, str]:
    """Build tool-to-module mapping by scanning tool files.

    This uses the same logic as lazy_tool_loader's dynamic discovery,
    ensuring the manifest includes accurate module paths for fallback loading.

    Returns:
        Dictionary mapping tool names to their module paths
    """
    tool_map: dict[str, str] = {}
    tools_dir = project_root / "src" / "unifi_access_mcp" / "tools"

    if not tools_dir.exists():
        logger.warning(f"Tools directory not found at {tools_dir}")
        return tool_map

    # Scan each .py file in tools directory
    for tool_file in tools_dir.glob("*.py"):
        if tool_file.name.startswith("_"):
            continue

        module_name = f"unifi_access_mcp.tools.{tool_file.stem}"

        try:
            content = tool_file.read_text()

            # Find tool names using pattern matching
            # Looking for: name="access_xxx" or name='access_xxx'
            pattern = r'name\s*=\s*["\'](access_[a-z_]+)["\']'
            matches = re.findall(pattern, content)

            for tool_name in matches:
                if tool_name.startswith("access_"):
                    tool_map[tool_name] = module_name

        except Exception as e:
            logger.warning(f"Error scanning {tool_file}: {e}")

    logger.info(f"   Built module map with {len(tool_map)} tool->module mappings")
    return tool_map


def generate_manifest() -> dict[str, Any]:
    """Generate tool manifest by forcing eager tool registration.

    This ensures all tools are properly registered through their decorators,
    providing full schemas with parameter information for LLMs.

    Returns:
        Dictionary with tool metadata for all tools
    """
    logger.info("Generating tool manifest with full schemas...")

    # Import the tool registry first
    from unifi_access_mcp.tool_index import TOOL_REGISTRY

    # CRITICAL: Import main.py to trigger the server.tool monkey-patch
    # This ensures @server.tool decorators call register_tool()
    logger.info("   Setting up permissioned tool decorator...")
    import unifi_access_mcp.main  # noqa: F401 - This monkey-patches server.tool with permissioned_tool

    # Force eager loading of all tools to populate TOOL_REGISTRY
    # We need to import the tool loader to trigger all tool registrations
    logger.info("   Loading all tools in eager mode to extract schemas...")

    try:
        # Import the auto loader which will trigger all tool registrations
        from unifi_mcp_shared.tool_loader import auto_load_tools

        # Load all tools - this will trigger all @server.tool decorators
        # which in turn call register_tool() to populate TOOL_REGISTRY
        auto_load_tools(base_package="unifi_access_mcp.tools")

        logger.info(f"   Loaded {len(TOOL_REGISTRY)} tools into registry")

    except Exception as e:
        logger.error(f"   Failed to load tools: {e}")
        import traceback

        traceback.print_exc()

        # Fallback to minimal manifest if tool loading fails
        logger.warning("   Falling back to minimal manifest from TOOL_MODULE_MAP")
        from unifi_access_mcp.categories import TOOL_MODULE_MAP

        tools = []
        for tool_name in sorted(TOOL_MODULE_MAP.keys()):
            tools.append({
                "name": tool_name,
                "description": f"Access tool: {tool_name}",
                "schema": {
                    "input": {"type": "object", "properties": {}},
                },
            })

        return {
            "tools": tools,
            "count": len(tools),
            "generated_by": "scripts/generate_tool_manifest.py",
            "note": "Fallback manifest with minimal schemas due to loading error.",
            "error": str(e),
        }

    # Extract annotations from FastMCP's internal tool registry
    from unifi_access_mcp.runtime import server

    annotations_map = get_tool_annotations(server)
    if annotations_map:
        logger.info(f"   Extracted annotations for {len(annotations_map)} tools")
    else:
        logger.warning("   No tool annotations found in FastMCP registry")

    # Build manifest from registry with full schemas
    tools = []
    for tool_name in sorted(TOOL_REGISTRY.keys()):
        meta = TOOL_REGISTRY[tool_name]

        tool_data = {
            "name": meta.name,
            "description": meta.description,
            "schema": {
                "input": meta.input_schema,
            },
        }

        # Include output schema if available
        if meta.output_schema:
            tool_data["schema"]["output"] = meta.output_schema

        # Include annotations if available from FastMCP registry
        if tool_name in annotations_map:
            tool_data["annotations"] = annotations_map[tool_name]

        tools.append(tool_data)

    # Build module map for fallback lazy loading
    module_map = build_module_map()

    manifest = {
        "tools": tools,
        "module_map": module_map,
        "count": len(tools),
        "generated_by": "scripts/generate_tool_manifest.py",
        "note": "Auto-generated with full schemas from tool decorators. Do not edit manually.",
    }

    logger.info(f"   Generated manifest with {len(tools)} tools and full schemas")

    # Log a sample tool to verify schemas are complete
    if tools:
        sample_tool = tools[0]
        logger.info(f"   Sample tool: {sample_tool['name']}")
        logger.info(f"      Properties: {list(sample_tool['schema']['input'].get('properties', {}).keys())}")

    return manifest


def main():
    """Generate and write tool manifest."""
    try:
        # Generate manifest
        manifest = generate_manifest()

        # Write to src/tools_manifest.json
        output_path = project_root / "src" / "unifi_access_mcp" / "tools_manifest.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            json.dump(manifest, f, indent=2, sort_keys=True)

        logger.info(f"   Wrote manifest to {output_path}")
        logger.info("   Tool manifest generation complete!")

        return 0

    except Exception as e:
        logger.error(f"   Failed to generate manifest: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
