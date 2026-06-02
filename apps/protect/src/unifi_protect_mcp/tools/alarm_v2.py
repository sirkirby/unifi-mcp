"""Alarm Manager v2 (read) tools for the UniFi Protect MCP server.

Reads the modern UniFi-OS Alarm Manager (``/api/v2/alarms/``), including
AI-powered alarms (e.g. AI Natural Language) that are not visible to the legacy
``protect_alarm_*`` tools. **Requires a SuperAdmin credential** — a Protect-scoped
account receives an actionable permission error explaining the requirement.
"""

import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.protect.managers.alarm_v2_manager import AlarmV2PermissionError
from unifi_protect_mcp.runtime import alarm_v2_manager, server

logger = logging.getLogger(__name__)


@server.tool(
    name="protect_alarm_v2_list_rules",
    description=(
        "Lists UniFi OS Alarm Manager v2 rules, including AI-powered alarms (e.g. AI "
        "Natural Language) that protect_alarm_list_rules cannot see. Each rule is "
        "normalized to id, title, triggers, actions, scope, and stats. Requires a "
        "SuperAdmin credential."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def protect_alarm_v2_list_rules() -> Dict[str, Any]:
    """List Alarm Manager v2 rules."""
    logger.info("protect_alarm_v2_list_rules tool called")
    try:
        rules = await alarm_v2_manager.list_rules()
        return {"success": True, "data": {"rules": rules, "count": len(rules)}}
    except AlarmV2PermissionError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error listing alarm v2 rules: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list alarm v2 rules: {e}"}


@server.tool(
    name="protect_alarm_v2_get_rule",
    description=(
        "Fetches a single UniFi OS Alarm Manager v2 rule by id (normalized). Requires a SuperAdmin credential."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def protect_alarm_v2_get_rule(
    rule_id: Annotated[str, Field(description="Alarm v2 rule id (UUID) from protect_alarm_v2_list_rules.")],
) -> Dict[str, Any]:
    """Get one Alarm Manager v2 rule."""
    logger.info("protect_alarm_v2_get_rule tool called for %s", rule_id)
    try:
        rule = await alarm_v2_manager.get_rule(rule_id)
        return {"success": True, "data": rule}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except AlarmV2PermissionError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting alarm v2 rule %s: %s", rule_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get alarm v2 rule: {e}"}


@server.tool(
    name="protect_alarm_v2_list_profiles",
    description=(
        "Lists UniFi OS Alarm Manager v2 arm profiles. Returns an empty list when no "
        "arm profiles are configured. Requires a SuperAdmin credential."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def protect_alarm_v2_list_profiles() -> Dict[str, Any]:
    """List Alarm Manager v2 arm profiles."""
    logger.info("protect_alarm_v2_list_profiles tool called")
    try:
        profiles = await alarm_v2_manager.list_profiles()
        return {"success": True, "data": {"profiles": profiles, "count": len(profiles)}}
    except AlarmV2PermissionError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error listing alarm v2 profiles: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list alarm v2 profiles: {e}"}
