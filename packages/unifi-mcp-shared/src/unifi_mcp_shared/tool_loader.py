"""Eager tool loader that dynamically imports tool modules.

Importing each module triggers the ``@server.tool`` decorators inside them,
which registers tools with the FastMCP server.

Generic version extracted from the network app. The ``base_package``
parameter is required (no default) so any MCP app can reuse this.
"""

import asyncio
import importlib
import logging
import pkgutil
from types import ModuleType
from typing import List, Optional, Set

logger = logging.getLogger(__name__)


def auto_load_tools(
    base_package: str,
    enabled_categories: Optional[List[str]] = None,
    enabled_tools: Optional[List[str]] = None,
    server=None,
    meta_tools: Optional[Set[str]] = None,
) -> None:
    """Dynamically import tool modules from *base_package*.

    Importing each module triggers the ``@server.tool`` decorators inside them,
    which registers tools with the FastMCP server.

    Args:
        base_package: The package containing tool modules (e.g. ``"unifi_network_mcp.tools"``).
        enabled_categories: If set, only load modules matching these category names
                           (e.g., ``["clients", "devices", "system"]``).
        enabled_tools: If set, load all modules but remove tools not in this list
                      (requires *server* parameter).
        server: FastMCP server instance (required if *enabled_tools* is set).
        meta_tools: Set of meta-tool names to always keep when filtering by
                    *enabled_tools*. Defaults to the standard five lazy-loading meta-tools.
    """
    try:
        tools_pkg: ModuleType = importlib.import_module(base_package)
    except ModuleNotFoundError as exc:
        logger.error("Tool package '%s' not found: %s", base_package, exc)
        return

    # Normalize enabled_categories to a set for fast lookup
    categories_filter = set(enabled_categories) if enabled_categories else None

    if categories_filter:
        logger.info("Auto-loading MCP tool modules (filtered by categories: %s)", list(categories_filter))
    elif enabled_tools:
        logger.info("Auto-loading MCP tool modules (will filter to %d specific tools)", len(enabled_tools))
    else:
        logger.info("Auto-loading MCP tool modules (all tools)")

    loaded_modules = []
    for mod_info in pkgutil.walk_packages(tools_pkg.__path__, tools_pkg.__name__ + "."):
        mod_name = mod_info.name
        simple_name = mod_name.rsplit(".", 1)[-1]

        # Skip private modules
        if simple_name.startswith("_"):
            continue

        # Filter by category if specified
        if categories_filter and simple_name not in categories_filter:
            logger.debug("Skipping module '%s' (not in enabled_categories)", mod_name)
            continue

        try:
            importlib.import_module(mod_name)
            loaded_modules.append(simple_name)
            logger.debug("Imported tool module: %s", mod_name)
        except Exception as exc:
            logger.warning("Failed to import tool module '%s': %s", mod_name, exc)

    logger.info("Loaded %d tool modules: %s", len(loaded_modules), loaded_modules)

    # If enabled_tools is specified, remove any tools not in the list
    if enabled_tools and server:
        enabled_set = set(enabled_tools)
        # Always keep meta-tools
        if meta_tools is None:
            meta_tools = {
                "unifi_tool_index",
                "unifi_execute",
                "unifi_batch",
                "unifi_batch_status",
                "unifi_load_tools",
            }
        enabled_set.update(meta_tools)

        try:

            async def filter_tools():
                tools = await server.list_tools()
                removed = []
                for tool in tools:
                    if tool.name not in enabled_set:
                        try:
                            server.remove_tool(tool.name)
                            removed.append(tool.name)
                        except Exception as e:
                            logger.warning("Failed to remove tool '%s': %s", tool.name, e)
                if removed:
                    logger.info("Removed %d tools not in enabled_tools list", len(removed))
                    logger.debug("Removed tools: %s", removed)

            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(filter_tools())
            else:
                loop.run_until_complete(filter_tools())
        except Exception as e:
            logger.warning("Failed to filter tools by enabled_tools: %s", e)

    logger.info("Finished auto-loading MCP tool modules")
