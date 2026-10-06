"""Eager tool loader that dynamically imports tool modules.

Importing each module triggers the ``@server.tool`` decorators inside them,
which registers tools with the FastMCP server.

Generic version extracted from the network app. The ``base_package``
parameter is required (no default) so any MCP app can reuse this.
"""

import importlib
import logging
import pkgutil
from types import ModuleType
from typing import Awaitable, List, Optional, Set

from unifi_mcp_shared.meta_tools import is_meta_tool

logger = logging.getLogger(__name__)


def auto_load_tools(
    base_package: str,
    enabled_categories: Optional[List[str]] = None,
    enabled_tools: Optional[List[str]] = None,
    server=None,
    meta_tools: Optional[Set[str]] = None,
) -> Awaitable[None] | None:
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
        meta_tools: Additional exact tool names to keep when filtering by
                    *enabled_tools*. Prefix-specific shared meta-tools are detected
                    automatically with :func:`is_meta_tool`.
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

    # If enabled_tools is specified, return an awaitable that removes and then
    # verifies disallowed tools. The startup caller must await it before
    # exposing a transport so there is no temporarily unconfined tool surface.
    if enabled_tools and server:
        enabled_set = set(enabled_tools)
        enabled_set.update(meta_tools or set())

        async def filter_tools() -> None:
            tools = await server.list_tools()
            removed = []
            for tool in tools:
                if tool.name not in enabled_set and not is_meta_tool(tool.name):
                    server.remove_tool(tool.name)
                    removed.append(tool.name)
            if removed:
                logger.info("Removed %d tools not in enabled_tools list", len(removed))
                logger.debug("Removed tools: %s", removed)

            remaining = await server.list_tools()
            unexpected = [
                tool.name for tool in remaining if tool.name not in enabled_set and not is_meta_tool(tool.name)
            ]
            if unexpected:
                raise RuntimeError("enabled_tools filtering left non-allowlisted tools registered")

        logger.info("Finished auto-loading MCP tool modules; enabled_tools filtering pending")
        return filter_tools()

    logger.info("Finished auto-loading MCP tool modules")
    return None
