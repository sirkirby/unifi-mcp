"""What references a network, read from the session API.

The Integration API references endpoint fails for networks that a firewall
policy or a switch-port override names, so the same dependencies are read here
from the session objects that hold them: WLANs, port profiles, device port
overrides, V2 firewall policies and clients.

Each family is read on its own. A family whose read fails is reported in
``unavailable`` and kept out of ``counts``, so a failed read never looks like a
network with no references.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.managers.client_manager import ClientManager
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.managers.device_manager import DeviceManager
from unifi_core.network.managers.firewall_manager import FirewallManager
from unifi_core.network.managers.network_manager import NetworkManager
from unifi_core.network.managers.switch_manager import SwitchManager

logger = logging.getLogger("unifi-network-mcp")


def _raw(obj: Any) -> Dict[str, Any]:
    """The controller payload behind an aiounifi item or a plain dict."""
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw
    return obj if isinstance(obj, dict) else {}


def _id_list(value: Any) -> List[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


class NetworkReferenceManager:
    """Reads which controller objects reference a network."""

    def __init__(
        self,
        connection_manager: ConnectionManager,
        *,
        network_manager: NetworkManager,
        switch_manager: SwitchManager,
        device_manager: DeviceManager,
        firewall_manager: FirewallManager,
        client_manager: ClientManager,
    ):
        self._connection = connection_manager
        self._networks = network_manager
        self._switches = switch_manager
        self._devices = device_manager
        self._firewall = firewall_manager
        self._clients = client_manager

    async def get_network_references(self, network_id: str, *, include_clients: bool = True) -> Dict[str, Any]:
        """Return every object that names ``network_id``.

        Raises:
            UniFiNotFoundError: no network on the controller has that id.
        """
        networks = await self._networks.get_networks()
        network = next((item for item in networks if _raw(item).get("_id") == network_id), None)
        if network is None:
            raise UniFiNotFoundError("network", network_id)

        families: Dict[str, List[Dict[str, Any]]] = {}
        unavailable: List[str] = []

        readers = {
            "wlans": self._wlans,
            "port_profiles": self._port_profiles,
            "device_port_overrides": self._device_port_overrides,
            "firewall_policies": self._firewall_policies,
        }
        if include_clients:
            readers["clients"] = self._clients_referencing

        for family, reader in readers.items():
            try:
                families[family] = await reader(network_id)
            except Exception as exc:
                logger.error("Error reading %s for network references: %s", family, type(exc).__name__)
                unavailable.append(family)

        return {
            "network_id": network_id,
            "name": _raw(network).get("name", ""),
            "references": families,
            "counts": {family: len(entries) for family, entries in families.items()},
            "unavailable": unavailable,
        }

    async def _wlans(self, network_id: str) -> List[Dict[str, Any]]:
        references = []
        for wlan in await self._networks.get_wlans():
            raw = _raw(wlan)
            networks = {raw.get("networkconf_id")}
            for key in raw.get("private_preshared_keys") or []:
                if isinstance(key, dict):
                    networks.add(key.get("networkconf_id"))
            if network_id in networks:
                references.append({"id": raw.get("_id", ""), "name": raw.get("name", "")})
        return references

    async def _port_profiles(self, network_id: str) -> List[Dict[str, Any]]:
        references = []
        for profile in await self._switches.get_port_profiles():
            raw = _raw(profile)
            roles = _roles(raw, network_id)
            if roles:
                references.append({"id": raw.get("_id", ""), "name": raw.get("name", ""), "role": roles})
        return references

    async def _device_port_overrides(self, network_id: str) -> List[Dict[str, Any]]:
        references = []
        for device in await self._devices.get_devices():
            raw = _raw(device)
            for override in raw.get("port_overrides") or []:
                if not isinstance(override, dict):
                    continue
                roles = _roles(override, network_id)
                if roles:
                    references.append(
                        {
                            "device_id": raw.get("_id", ""),
                            "port_idx": override.get("port_idx"),
                            "role": roles,
                        }
                    )
        return references

    async def _firewall_policies(self, network_id: str) -> List[Dict[str, Any]]:
        references = []
        for policy in await self._firewall.get_firewall_policies(include_predefined=False):
            raw = _raw(policy)
            source = raw.get("source")
            destination = raw.get("destination")
            in_source = network_id in _id_list(source.get("network_ids") if isinstance(source, dict) else None)
            in_destination = network_id in _id_list(
                destination.get("network_ids") if isinstance(destination, dict) else None
            )
            if in_source or in_destination:
                direction = "both" if in_source and in_destination else ("source" if in_source else "destination")
                references.append({"id": raw.get("_id", ""), "name": raw.get("name", ""), "direction": direction})
        return references

    async def _clients_referencing(self, network_id: str) -> List[Dict[str, Any]]:
        references = []
        for client in await self._clients.get_clients(include_offline=False):
            raw = _raw(client)
            if raw.get("network_id") == network_id or raw.get("virtual_network_override_id") == network_id:
                references.append({"mac": raw.get("mac", ""), "hostname": raw.get("hostname", "")})
        return references


def _roles(raw: Dict[str, Any], network_id: str) -> List[str]:
    """The ways a port profile or port override names the network."""
    roles = []
    if raw.get("native_networkconf_id") == network_id:
        roles.append("native")
    if network_id in _id_list(raw.get("tagged_networkconf_ids")):
        roles.append("tagged")
    if network_id in _id_list(raw.get("excluded_networkconf_ids")):
        roles.append("excluded")
    return roles
