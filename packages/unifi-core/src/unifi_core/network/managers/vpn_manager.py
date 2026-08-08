"""VPN management for UniFi Network MCP server.

VPN configurations are stored in the networkconf API endpoint alongside regular
networks. They're identified by the 'purpose' field (vpn-client, vpn-server,
remote-user-vpn) and/or 'vpn_type' field (wireguard-client, openvpn-server, etc).

Note: UniFi is developing a dedicated VPN API but it's not yet complete.
This implementation uses the networkconf endpoint which is the reliable approach.
"""

import logging
from typing import Any, Dict, List, Tuple

from aiounifi.models.api import ApiRequest

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.merge import deep_merge
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.write_verification import WriteVerificationResult, failed_write, verify_write

logger = logging.getLogger("unifi-network-mcp")

CACHE_PREFIX_VPN_CONFIGS = "vpn_configs"
CACHE_PREFIX_NETWORKS = "networks"


def is_vpn_network(network: Dict[str, Any]) -> bool:
    """Check if a network configuration represents a VPN entity.

    Args:
        network: Network configuration dictionary

    Returns:
        True if this is a VPN configuration
    """
    purpose = str(network.get("purpose", "")).lower()
    vpn_type = str(network.get("vpn_type", "")).lower()

    return (
        purpose.startswith("vpn")
        or purpose in {"remote-user-vpn", "vpn-client", "vpn-server"}
        or "vpn" in vpn_type
        or "wireguard" in vpn_type
        or "openvpn" in vpn_type
    )


def classify_vpn_type(purpose: str, vpn_type: str) -> Tuple[bool, bool]:
    """Classify VPN configuration as client or server.

    Args:
        purpose: The purpose field from VPN config
        vpn_type: The vpn_type field from VPN config

    Returns:
        Tuple of (is_client, is_server)
    """
    purpose = str(purpose).lower() if purpose else ""
    vpn_type = str(vpn_type).lower() if vpn_type else ""

    is_client = purpose == "vpn-client" or "client" in vpn_type or vpn_type in {"wireguard-client", "openvpn-client"}

    is_server = (
        purpose in {"vpn-server", "remote-user-vpn"}
        or "server" in vpn_type
        or vpn_type in {"wireguard-server", "openvpn-server"}
    )

    return is_client, is_server


class VpnManager:
    """Manages VPN-related operations on the Unifi Controller.

    VPN configurations are retrieved from the networkconf API and filtered
    based on purpose and vpn_type fields.
    """

    def __init__(self, connection_manager: ConnectionManager):
        """Initialize the VPN Manager.

        Args:
            connection_manager: The shared ConnectionManager instance.
        """
        self._connection = connection_manager

    async def _get_all_network_configs(self) -> List[Dict[str, Any]]:
        """Get all network configurations from the controller.

        Returns:
            List of network configuration dictionaries
        """
        cache_key = f"{CACHE_PREFIX_NETWORKS}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key)
        if cached_data is not None:
            return cached_data

        try:
            api_request = ApiRequest(method="get", path="/rest/networkconf")
            response = await self._connection.request(api_request)

            # Handle known response formats and fail closed on malformed data.
            if isinstance(response, dict) and "data" in response:
                networks = response["data"]
            elif isinstance(response, list):
                networks = response
            else:
                raise RuntimeError("Controller returned an invalid networkconf response")
            if not isinstance(networks, list) or not all(isinstance(item, dict) for item in networks):
                raise RuntimeError("Controller returned malformed entries in the networkconf response")

            self._connection._update_cache(cache_key, networks)
            return networks
        except Exception as e:
            logger.error("Error fetching network configurations: %s", e)
            raise

    async def get_vpn_configs(self, include_clients: bool = True, include_servers: bool = True) -> List[Dict[str, Any]]:
        """Get VPN configurations from the controller.

        Args:
            include_clients: Whether to include VPN client configurations
            include_servers: Whether to include VPN server configurations

        Returns:
            List of VPN configuration dictionaries
        """
        cache_key = f"{CACHE_PREFIX_VPN_CONFIGS}_{self._connection.site}_{include_clients}_{include_servers}"
        cached_data = self._connection.get_cached(cache_key)
        if cached_data is not None:
            return cached_data

        try:
            networks = await self._get_all_network_configs()
            vpn_configs = []

            for network in networks:
                if not is_vpn_network(network):
                    continue

                purpose = network.get("purpose", "")
                vpn_type = network.get("vpn_type", "")
                is_client, is_server = classify_vpn_type(purpose, vpn_type)

                if (include_clients and is_client) or (include_servers and is_server):
                    vpn_configs.append(network)
                    logger.debug(
                        "Found VPN config: %s (purpose=%s, vpn_type=%s, client=%s, server=%s)",
                        network.get("name", "unnamed"),
                        purpose,
                        vpn_type,
                        is_client,
                        is_server,
                    )

            logger.debug("Found %s VPN configurations", len(vpn_configs))
            self._connection._update_cache(cache_key, vpn_configs)
            return vpn_configs

        except Exception as e:
            logger.error("Error getting VPN configurations: %s", e)
            raise

    async def get_vpn_clients(self) -> List[Dict[str, Any]]:
        """Get list of VPN client configurations for the current site.

        Returns:
            List of VPN client configuration dictionaries
        """
        return await self.get_vpn_configs(include_clients=True, include_servers=False)

    async def get_vpn_servers(self) -> List[Dict[str, Any]]:
        """Get list of VPN server configurations for the current site.

        Returns:
            List of VPN server configuration dictionaries
        """
        return await self.get_vpn_configs(include_clients=False, include_servers=True)

    async def get_vpn_client_details(self, client_id: str) -> Dict[str, Any]:
        """Get detailed information for a specific VPN client.

        Raises:
            UniFiNotFoundError: If the client does not exist.
        """
        vpn_clients = await self.get_vpn_clients()
        client = next((c for c in vpn_clients if c.get("_id") == client_id), None)
        if client is None:
            raise UniFiNotFoundError("vpn_client", client_id)
        return client

    async def get_vpn_server_details(self, server_id: str) -> Dict[str, Any]:
        """Get detailed information for a specific VPN server.

        Raises:
            UniFiNotFoundError: If the server does not exist.
        """
        vpn_servers = await self.get_vpn_servers()
        server = next((s for s in vpn_servers if s.get("_id") == server_id), None)
        if server is None:
            raise UniFiNotFoundError("vpn_server", server_id)
        return server

    def _invalidate_vpn_caches(self) -> None:
        """Invalidate networkconf and every VPN classification cache."""
        self._connection._invalidate_cache(f"{CACHE_PREFIX_NETWORKS}_{self._connection.site}")
        for suffix in ["_True_True", "_True_False", "_False_True"]:
            self._connection._invalidate_cache(f"{CACHE_PREFIX_VPN_CONFIGS}_{self._connection.site}{suffix}")

    async def _update_vpn_config(
        self,
        config_id: str,
        update_data: Dict[str, Any],
        *,
        existing: Dict[str, Any] | None = None,
    ) -> WriteVerificationResult:
        """Fetch-merge-update a VPN config and verify exact persisted values."""
        try:
            if existing is None:
                networks = await self._get_all_network_configs()
                existing = next((n for n in networks if n.get("_id") == config_id), None)

            if not existing:
                raise UniFiNotFoundError("vpn_config", config_id)

            # Merge updates into existing config (deep merge preserves nested sub-objects)
            merged_data = deep_merge(existing, update_data)

            api_request = ApiRequest(
                method="put",
                path=f"/rest/networkconf/{config_id}",
                data=merged_data,
            )
            await self._connection.request(api_request)

            logger.info("Updated VPN configuration %s", config_id)

            self._invalidate_vpn_caches()
            try:
                networks = await self._get_all_network_configs()
                refetched = next((network for network in networks if network.get("_id") == config_id), None)
            except Exception as e:
                return failed_write(
                    f"Controller accepted the VPN update but the resource could not be re-read: {e}",
                    operation="update",
                    mutation_applied=True,
                    metadata={"vpn_id": config_id, "details_before_attempt": existing},
                )
            if refetched is None:
                return failed_write(
                    "Controller accepted the VPN update but the resource disappeared before verification",
                    operation="update",
                    mutation_applied=True,
                    metadata={"vpn_id": config_id, "details_before_attempt": existing},
                )
            return verify_write(
                operation="update",
                requested=update_data,
                before=existing,
                after=refetched,
                # Legacy networkconf omits default-true 'enabled' on persist;
                # absent means enabled, not a dropped write.
                absent_value_defaults={"enabled": True},
                metadata={"vpn_id": config_id},
            )

        except Exception as e:
            logger.error("Error updating VPN configuration %s: %s", config_id, e)
            raise

    async def update_vpn_client_state(self, client_id: str, enabled: bool) -> WriteVerificationResult:
        """Update a VPN client's enabled state and return exact write verification."""
        client = await self.get_vpn_client_details(client_id)  # raises on miss

        result = await self._update_vpn_config(client_id, {"enabled": enabled}, existing=client)
        if result.success:
            logger.info("VPN client %s %s", client.get("name", client_id), "enabled" if enabled else "disabled")
        return result

    async def delete_vpn_client(self, client_id: str) -> bool:
        """Delete a VPN client and verify its networkconf entry is absent."""
        client = await self.get_vpn_client_details(client_id)
        try:
            await self._connection.request(ApiRequest(method="delete", path=f"/rest/networkconf/{client_id}"))
            self._invalidate_vpn_caches()
            networks = await self._get_all_network_configs()
            if any(network.get("_id") == client_id for network in networks):
                raise RuntimeError("Controller accepted the delete request but the VPN client still exists")
            logger.info("Deleted VPN client %s", client.get("name", client_id))
            return True
        except Exception as e:
            logger.error("Error deleting VPN client %s: %s", client_id, e, exc_info=True)
            raise

    async def update_vpn_server_state(self, server_id: str, enabled: bool) -> WriteVerificationResult:
        """Update a VPN server's enabled state and return exact write verification."""
        server = await self.get_vpn_server_details(server_id)  # raises on miss

        result = await self._update_vpn_config(server_id, {"enabled": enabled}, existing=server)
        if result.success:
            logger.info("VPN server %s %s", server.get("name", server_id), "enabled" if enabled else "disabled")
        return result

    async def toggle_vpn_config(self, config_id: str) -> WriteVerificationResult:
        """Toggle a VPN configuration's enabled state.

        Args:
            config_id: ID of the VPN configuration to toggle

        Returns:
            Structured exact field-verification result
        """
        networks = await self._get_all_network_configs()
        config = next((n for n in networks if n.get("_id") == config_id), None)

        if not config or not is_vpn_network(config):
            raise UniFiNotFoundError("vpn_config", config_id)

        new_state = not config.get("enabled", True)
        return await self._update_vpn_config(config_id, {"enabled": new_state}, existing=config)
