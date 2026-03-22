"""Shared MCP server patterns: permissions, confirmation, lazy loading, config, diagnostics, jobs, validators."""

from unifi_mcp_shared.config import load_yaml_config, setup_logging
from unifi_mcp_shared.config_helpers import parse_config_bool
from unifi_mcp_shared.confirmation import (
    create_preview,
    preview_response,
    should_auto_confirm,
    toggle_preview,
    update_preview,
)
from unifi_mcp_shared.formatting import error_response, success_response
from unifi_mcp_shared.jobs import JOBS, JobStore, get_job_status, start_async_tool
from unifi_mcp_shared.manifest_helpers import get_tool_annotations
from unifi_mcp_shared.lazy_tools import (
    LazyToolLoader,
    build_tool_module_map,
    setup_lazy_loading,
)
from unifi_mcp_shared.meta_tools import register_load_tools, register_meta_tools
from unifi_mcp_shared.permissions import PermissionChecker
from unifi_mcp_shared.tool_loader import auto_load_tools
from unifi_mcp_shared.validators import ResourceValidator, create_response

__all__ = [
    "JOBS",
    "JobStore",
    "LazyToolLoader",
    "PermissionChecker",
    "ResourceValidator",
    "auto_load_tools",
    "build_tool_module_map",
    "create_preview",
    "create_response",
    "error_response",
    "get_tool_annotations",
    "get_job_status",
    "load_yaml_config",
    "parse_config_bool",
    "preview_response",
    "register_load_tools",
    "register_meta_tools",
    "setup_lazy_loading",
    "setup_logging",
    "should_auto_confirm",
    "start_async_tool",
    "success_response",
    "toggle_preview",
    "update_preview",
]
