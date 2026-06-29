"""Unifi Network MCP gateway (USG) settings tools.

Read and update the gateway's security / NAT / connection-tracking settings --
the controller's ``usg`` settings singleton. Updates deep-merge a partial onto
the current object, so nested sub-objects (e.g. ``dns_verification``) and
untouched sibling keys are preserved.
"""

import json
import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.confirmation import update_preview
from unifi_core.network.models.gateway_settings import (
    from_controller as gw_from_controller,
)
from unifi_core.network.models.gateway_settings import (
    to_controller_update as gw_to_update,
)
from unifi_core.redaction import redact_sensitive_fields
from unifi_network_mcp.runtime import (
    gateway_settings_manager,
    server,
    should_redact_sensitive_fields,
)

logger = logging.getLogger(__name__)

# Fields whose change affects gateway-wide reachability or security posture.
# Surfaces an explicit warning in the confirm-preview.
SECURITY_SENSITIVE_FIELDS: frozenset[str] = frozenset(
    {
        # UPnP / NAT-PMP
        "upnp_enabled",
        "upnp_nat_pmp_enabled",
        "upnp_secure_mode",
        "upnp_wan_interface",
        # GeoIP filtering
        "geo_ip_filtering_enabled",
        "geo_ip_filtering_block",
        "geo_ip_filtering_countries",
        "geo_ip_filtering_traffic_direction",
        # DNS verification (changes the gateway's upstream resolver -- a DNS-redirection lever)
        "dns_verification",
        # Flood/amplification protections
        "syn_cookies",
        "broadcast_ping",
        # ICMP redirect controls
        "send_redirects",
        "receive_redirects",
        # MSS clamp
        "mss_clamp",
        # Hardware offloading
        "offload_accounting",
        "offload_l2_blocking",
        "offload_sch",
        # Conntrack timeouts
        "icmp_timeout",
        "other_timeout",
        "udp_stream_timeout",
        "udp_other_timeout",
        "tcp_established_timeout",
        "tcp_close_timeout",
        "tcp_close_wait_timeout",
        "tcp_fin_wait_timeout",
        "tcp_last_ack_timeout",
        "tcp_syn_recv_timeout",
        "tcp_syn_sent_timeout",
        "tcp_time_wait_timeout",
        "timeout_setting_preference",
    }
)


@server.tool(
    name="unifi_get_gateway_settings",
    description="Get the gateway (USG) settings: security (GeoIP filtering, SYN cookies, ICMP "
    "redirects, DNS verification), NAT/UPnP (UPnP, NAT-PMP, MSS clamp), connection-tracking ALG "
    "modules (FTP/GRE/H.323/PPTP/SIP/TFTP), hardware offloading, and conntrack timeouts. "
    "Read-only; use unifi_update_gateway_settings to change values.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_gateway_settings() -> Dict[str, Any]:
    """Get the gateway (USG) settings for the current site.

    Returns:
        Dict: Success status plus the gateway settings, or an error message.
    """
    logger.info("unifi_get_gateway_settings tool called")
    redact_sensitive = should_redact_sensitive_fields()
    try:
        raw = await gateway_settings_manager.get_gateway_settings()
        shaped = gw_from_controller(raw).model_dump(exclude_none=True)
        return redact_sensitive_fields(
            {"success": True, "settings": shaped},
            redact_sensitive=redact_sensitive,
        )
    except Exception as e:
        logger.error("Error getting gateway settings: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to get gateway settings: {e}"}


@server.tool(
    name="unifi_update_gateway_settings",
    description="Update gateway (USG) settings. Pass only the fields you want to change; current "
    "values (including nested sub-objects) are automatically preserved via deep-merge. "
    "Security: geo_ip_filtering_enabled (bool), geo_ip_filtering_block ('block'/'allow'), "
    "geo_ip_filtering_countries (CSV ISO codes), geo_ip_filtering_traffic_direction "
    "('both'/'ingress'/'egress'), syn_cookies (bool), broadcast_ping (bool), receive_redirects (bool), "
    "send_redirects (bool), dns_verification (object). "
    "NAT/UPnP: upnp_enabled (bool), upnp_nat_pmp_enabled (bool), upnp_secure_mode (bool), "
    "upnp_wan_interface (str), mss_clamp ('auto'/'custom'/'disabled'). "
    "ALG modules: ftp_module, gre_module, h323_module, pptp_module, sip_module, tftp_module (bool). "
    "Offloading: offload_accounting (bool), offload_l2_blocking (bool), offload_sch (bool). "
    "Conntrack timeouts (int seconds): icmp_timeout, other_timeout, udp_stream_timeout, "
    "udp_other_timeout, tcp_established_timeout, tcp_close_timeout, tcp_close_wait_timeout, "
    "tcp_fin_wait_timeout, tcp_last_ack_timeout, tcp_syn_recv_timeout, tcp_syn_sent_timeout, "
    "tcp_time_wait_timeout, timeout_setting_preference ('auto'/'manual'). Misc: unbind_wan_monitors (bool). "
    "WARNING: changing security/NAT settings (UPnP/NAT-PMP, GeoIP filtering, DNS verification, SYN "
    "cookies, broadcast-ping, ICMP redirects, MSS clamp, offloading, or conntrack timeouts) affects "
    "gateway-wide security/NAT/reachability. Requires confirmation.",
    permission_category="gateway_settings",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_gateway_settings(
    update_data: Annotated[
        Dict[str, Any],
        Field(description="Dictionary of gateway settings fields to update. See tool description."),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, applies the update. When false (default), returns a preview."),
    ] = False,
) -> Dict[str, Any]:
    """Update the gateway (USG) settings.

    Only provided fields are changed; everything else (and nested sub-object
    siblings) is preserved via deep-merge. Requires confirmation.

    Returns:
        Dict: Success status, updated fields, and the new settings, or an error.
    """
    logger.info("unifi_update_gateway_settings tool called (confirm=%s)", confirm)
    redact_sensitive = should_redact_sensitive_fields()
    if not update_data:
        return {"success": False, "error": "update_data cannot be empty"}

    validated_data = gw_to_update(update_data)
    if not validated_data:
        return {"success": False, "error": "No valid mutable fields provided for update."}

    current = await gateway_settings_manager.get_gateway_settings()

    if not confirm:
        sensitive = sorted(set(validated_data) & SECURITY_SENSITIVE_FIELDS)
        warnings = None
        if sensitive:
            warnings = [
                "WARNING: Changing "
                + ", ".join(sensitive)
                + " affects gateway-wide security / NAT / connection-tracking behavior and can "
                "impact reachability or security posture. Verify the values before setting confirm=true."
            ]
        return redact_sensitive_fields(
            update_preview(
                resource_type="gateway_settings",
                resource_id="usg",
                resource_name="Gateway Settings",
                current_state=current,
                updates=validated_data,
                warnings=warnings,
            ),
            redact_sensitive=redact_sensitive,
        )

    updated_fields_list = list(validated_data.keys())
    logger.info("Attempting to update gateway settings with fields: %s", ", ".join(updated_fields_list))
    try:
        success, error_detail = await gateway_settings_manager.update_gateway_settings(validated_data)
        if success:
            updated = await gateway_settings_manager.get_gateway_settings()
            logger.info("Successfully updated gateway settings")
            return redact_sensitive_fields(
                {
                    "success": True,
                    "updated_fields": updated_fields_list,
                    "settings": json.loads(json.dumps(updated, default=str)),
                },
                redact_sensitive=redact_sensitive,
            )
        logger.error("Failed to update gateway settings: %s", error_detail)
        return {"success": False, "error": f"Failed to update gateway settings: {error_detail}"}
    except Exception as e:
        logger.error("Error updating gateway settings: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to update gateway settings: {e}"}
