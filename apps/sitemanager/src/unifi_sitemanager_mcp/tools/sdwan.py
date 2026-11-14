"""SD-WAN tools: Site Magic configurations and their deployment status."""

import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_sitemanager_mcp.runtime import sdwan_manager, server, tool_failure, tool_success

logger = logging.getLogger(__name__)

ConfigId = Annotated[str, Field(description="SD-WAN configuration id, from sitemanager_list_sdwan_configs.")]


@server.tool(
    name="sitemanager_list_sdwan_configs",
    title="List SD-WAN Configs",
    description=(
        "Lists the SD-WAN configurations on the account behind the Site Manager API key. An account with none "
        "returns an empty list."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="sdwan",
    permission_action="read",
    auth="api_key_only",
)
async def sitemanager_list_sdwan_configs() -> Dict[str, Any]:
    """List SD-WAN configurations."""
    logger.info("sitemanager_list_sdwan_configs tool called")
    try:
        configs = await sdwan_manager.list_configs()
        return tool_success(
            {"configs": [config.model_dump(exclude_none=True) for config in configs], "count": len(configs)}
        )
    except Exception as e:
        return tool_failure("list SD-WAN configurations", e)


@server.tool(
    name="sitemanager_get_sdwan_config",
    title="Get SD-WAN Config",
    description="Returns one SD-WAN configuration with its settings, hubs and spokes.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="sdwan",
    permission_action="read",
    auth="api_key_only",
)
async def sitemanager_get_sdwan_config(config_id: ConfigId) -> Dict[str, Any]:
    """Get one SD-WAN configuration."""
    logger.info("sitemanager_get_sdwan_config tool called")
    try:
        config = await sdwan_manager.get_config(config_id)
        return tool_success({"config": config.model_dump(exclude_none=True)})
    except Exception as e:
        return tool_failure("get SD-WAN configuration", e)


@server.tool(
    name="sitemanager_get_sdwan_config_status",
    title="Get SD-WAN Config Status",
    description=(
        "Returns the deployment status of one SD-WAN configuration: generation status, errors and warnings, "
        "and per-hub and per-spoke state."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="sdwan",
    permission_action="read",
    auth="api_key_only",
)
async def sitemanager_get_sdwan_config_status(config_id: ConfigId) -> Dict[str, Any]:
    """Get the deployment status of one SD-WAN configuration."""
    logger.info("sitemanager_get_sdwan_config_status tool called")
    try:
        status = await sdwan_manager.get_config_status(config_id)
        return tool_success({"status": status.model_dump(exclude_none=True)})
    except Exception as e:
        return tool_failure("get SD-WAN configuration status", e)
