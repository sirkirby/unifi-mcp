"""Lazy tool loader for on-demand tool registration.

This module implements true lazy loading of tools, registering them only
when first called by an LLM. This dramatically reduces initial context usage.

Generic parts extracted from unifi_network_mcp so any MCP app can reuse them.
"""

import importlib
import json
import logging
import re
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, Set

logger = logging.getLogger(__name__)


def build_tool_module_map(
    tools_package: str,
    manifest_path: str | Path | None = None,
    tool_prefix: str = "unifi_",
) -> Dict[str, str]:
    """Build tool-to-module mapping by scanning tool files.

    Dynamically discovers all tools and their modules by scanning Python files
    in *tools_package* for ``name="..."`` patterns in decorators.

    Falls back to loading from *manifest_path* (a ``tools_manifest.json``) if
    the tools directory cannot be found.

    Args:
        tools_package: Dotted Python package name containing the tool modules
                       (e.g. ``"unifi_network_mcp.tools"``).
        manifest_path: Optional path to a pre-generated ``tools_manifest.json``.
                       Used as fallback when the package directory cannot be
                       resolved on disk.
        tool_prefix: Prefix for tool names to discover (default ``"unifi_"``).
                     Use ``"protect_"`` for Protect tools.

    Returns:
        Dictionary mapping tool names to their dotted module paths.
    """
    tool_map: Dict[str, str] = {}

    # Resolve the tools directory from the package name
    tools_dir: Path | None = None
    try:
        pkg = importlib.import_module(tools_package)
        if hasattr(pkg, "__path__"):
            tools_dir = Path(pkg.__path__[0])
    except (ModuleNotFoundError, Exception) as exc:
        logger.debug("Could not import tools package '%s': %s", tools_package, exc)

    if tools_dir is None or not tools_dir.exists():
        logger.warning("Tools directory not found for package '%s', falling back to manifest", tools_package)
        return _load_module_map_from_manifest(manifest_path)

    # Scan each .py file in tools directory
    # Escape prefix for regex safety
    escaped_prefix = re.escape(tool_prefix)
    for tool_file in tools_dir.glob("*.py"):
        if tool_file.name.startswith("_"):
            continue

        module_name = f"{tools_package}.{tool_file.stem}"

        try:
            content = tool_file.read_text()

            # Find tool names matching the configured prefix
            pattern = rf'name\s*=\s*["\']({escaped_prefix}[a-z_]+)["\']'
            matches = re.findall(pattern, content)

            for tool_name in matches:
                if tool_name.startswith(tool_prefix):
                    tool_map[tool_name] = module_name

        except Exception as exc:
            logger.debug("Error scanning %s: %s", tool_file, exc)

    logger.debug("Built dynamic tool map with %d tools for package '%s'", len(tool_map), tools_package)
    return tool_map


def _load_module_map_from_manifest(manifest_path: str | Path | None) -> Dict[str, str]:
    """Load tool-to-module mapping from a manifest file.

    Args:
        manifest_path: Path to the tools_manifest.json file.

    Returns:
        Dictionary mapping tool names to module paths, or empty dict if unavailable.
    """
    if manifest_path is None:
        logger.warning("No manifest path provided for fallback loading")
        return {}

    path = Path(manifest_path)
    if not path.exists():
        logger.warning("Tools manifest not found at %s", path)
        return {}

    try:
        with open(path) as f:
            manifest = json.load(f)
        module_map = manifest.get("module_map", {})
        logger.info("Loaded module map from manifest with %d tools", len(module_map))
        return module_map
    except Exception as exc:
        logger.warning("Failed to load module map from manifest: %s", exc)
        return {}


class LazyToolLoader:
    """Manages lazy/on-demand tool loading."""

    def __init__(self, server, tool_decorator: Callable, tool_module_map: Dict[str, str]):
        """Initialize the lazy tool loader.

        Args:
            server: FastMCP server instance
            tool_decorator: The decorator function to register tools
            tool_module_map: Mapping of tool names to their module paths
        """
        self.server = server
        self.tool_decorator = tool_decorator
        self.tool_module_map = tool_module_map
        self.loaded_modules: Set[str] = set()
        self.loaded_tools: Set[str] = set()
        self._loading = False

        logger.info("Lazy tool loader initialized")

    def is_loaded(self, tool_name: str) -> bool:
        """Check if a tool is already loaded."""
        return tool_name in self.loaded_tools

    async def load_tool(self, tool_name: str) -> bool:
        """Load a tool on-demand.

        Args:
            tool_name: Name of the tool to load

        Returns:
            True if tool was loaded successfully, False otherwise
        """
        # Avoid recursive loading
        if self._loading:
            return False

        if self.is_loaded(tool_name):
            logger.debug("Tool '%s' already loaded", tool_name)
            return True

        module_path = self.tool_module_map.get(tool_name)
        if not module_path:
            logger.warning("No module mapping found for tool '%s'", tool_name)
            return False

        try:
            self._loading = True
            logger.info("Lazy-loading tool '%s' from '%s'", tool_name, module_path)

            # Import the module (this will trigger @server.tool decorators)
            if module_path not in self.loaded_modules:
                importlib.import_module(module_path)
                self.loaded_modules.add(module_path)

            # Mark tool as loaded
            self.loaded_tools.add(tool_name)

            logger.info("Tool '%s' loaded successfully", tool_name)
            return True

        except Exception as exc:
            logger.error("Failed to load tool '%s': %s", tool_name, exc, exc_info=True)
            return False
        finally:
            self._loading = False

    async def intercept_call_tool(
        self,
        original_call_tool: Callable,
        name: str,
        arguments: dict,
        context: Any | None = None,
    ) -> Any:
        """Intercept tool calls to load tools on-demand.

        Args:
            original_call_tool: Original call_tool method
            name: Tool name
            arguments: Tool arguments

        Returns:
            Result from the tool execution
        """
        # Try to load the tool if not already loaded
        if not self.is_loaded(name) and name in self.tool_module_map:
            loaded = await self.load_tool(name)
            if not loaded:
                raise ValueError(f"Failed to load tool '{name}'")

        # Call the original method
        return await original_call_tool(name, arguments, context=context)


def setup_lazy_loading(server, tool_decorator: Callable, tool_module_map: Dict[str, str]) -> LazyToolLoader:
    """Setup lazy tool loading by intercepting call_tool.

    Args:
        server: FastMCP server instance
        tool_decorator: The decorator function to register tools
        tool_module_map: Mapping of tool names to their module paths

    Returns:
        LazyToolLoader instance
    """
    loader = LazyToolLoader(server, tool_decorator, tool_module_map)

    # Intercept call_tool to load tools on-demand
    original_call_tool = server.call_tool

    @wraps(original_call_tool)
    async def lazy_call_tool(name: str, arguments: dict, context: Any | None = None):
        return await loader.intercept_call_tool(original_call_tool, name, arguments, context=context)

    server.call_tool = lazy_call_tool

    logger.info("Lazy tool loading enabled - tools will be loaded on first use")

    return loader
