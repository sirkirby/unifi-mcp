"""Shared public read views for UniFi Network manager results.

Managers return controller-domain objects.  Both the Network MCP app and the
catalog-driven API expose richer filtering and shaping on top of those objects.
The pure functions in this module are the single source of truth for that
public contract; they perform no controller I/O and import no app packages.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from unifi_core.network.models.clients import _is_online, client_from_controller
from unifi_core.network.models.devices import normalize_radio_channel
from unifi_core.network.models.firewall import SELECTOR_ACTIVATORS
from unifi_core.network.models.firewall import from_controller as firewall_policy_from_controller
from unifi_core.network.models.networks import from_controller as network_from_controller

LEGACY_ENGINE_HINT = (
    "No zone-based firewall configuration was returned. This site may still be running the "
    "legacy (pre-zone-based) firewall engine, whose rules are not visible here. Call "
    "unifi_list_legacy_firewall_rules before concluding that no firewall rules are configured."
)

_POWER_DEVICE_MODELS = {"UP1", "UP6", "USP"}
_DASHBOARD_TIMESERIES_SECTIONS = frozenset(
    {
        "radio_activity",
        "wan_activity",
        "wan_history",
        "wifi_activity",
    }
)


def _raw(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    raw = getattr(value, "raw", None)
    return raw if isinstance(raw, dict) else {}


def classify_device(device: dict[str, Any]) -> str:
    """Classify a raw controller device into its public semantic category."""
    device_type = device.get("type", "")
    model = device.get("model", "")
    if device_type.startswith("usp"):
        return "pdu"
    if device_type.startswith("uap"):
        is_ap = device.get("is_access_point")
        if is_ap is not None:
            return "ap" if is_ap else "pdu"
        if any(model.upper().startswith(prefix) for prefix in _POWER_DEVICE_MODELS):
            return "pdu"
        return "ap"
    if device_type[:3] in ("usw", "usk"):
        return "switch"
    if device_type[:3] in ("ugw", "udm", "uxg"):
        return "gateway"
    if device_type == "uci":
        return "wan"
    return "unknown"


def get_wifi_bands(device: dict[str, Any]) -> list[str]:
    """Return stable display names for active radios."""
    bands = set()
    for radio in device.get("radio_table", []):
        if radio.get("radio") == "na":
            bands.add("5GHz")
        elif radio.get("radio") == "ng":
            bands.add("2.4GHz")
        elif radio.get("radio") == "wifi6e":
            bands.add("6GHz")
    return sorted(bands)


def shape_client_list(
    clients: list[Any],
    *,
    site: str,
    filter_type: str = "all",
    search: str | None = None,
    limit: int = 100,
    fields: str | None = None,
) -> dict[str, Any]:
    """Apply the public client-list filters, projection, and envelope."""
    clients_raw = [_raw(client) for client in clients]
    if filter_type == "wireless":
        clients_raw = [client for client in clients_raw if not client.get("is_wired", False)]
    elif filter_type == "wired":
        clients_raw = [client for client in clients_raw if client.get("is_wired", False)]

    if search and search.strip():
        search_lower = search.strip().lower()
        clients_raw = [
            client
            for client in clients_raw
            if search_lower in (client.get("name") or "").lower()
            or search_lower in (client.get("hostname") or "").lower()
            or search_lower in (client.get("ip") or "").lower()
            or search_lower in (client.get("mac") or "").lower()
        ]

    total_count = len(clients_raw)
    clients_raw = clients_raw[:limit]
    known_fields = {
        "mac",
        "name",
        "hostname",
        "ip",
        "connection_type",
        "status",
        "last_seen",
        "_id",
        "essid",
        "signal_dbm",
        "channel",
        "radio",
    }
    requested_fields: set[str] | None = None
    unknown_fields: list[str] = []
    if fields and fields.strip():
        requested_fields = {field.strip() for field in fields.split(",")}
        unknown_fields = sorted(requested_fields - known_fields)

    formatted_clients = []
    for client in clients_raw:
        full_data = client_from_controller(client).model_dump(exclude_none=True)
        full_data["connection_type"] = "Wired" if client.get("is_wired", False) else "Wireless"
        full_data["_id"] = client.get("_id")
        if not client.get("is_wired", False):
            full_data["essid"] = client.get("essid", "Unknown")
            full_data["signal_dbm"] = client.get("signal")
            full_data["channel"] = client.get("channel", "Unknown")
            full_data["radio"] = client.get("radio", "Unknown")
        formatted_clients.append(
            {key: value for key, value in full_data.items() if key in requested_fields}
            if requested_fields
            else full_data
        )

    response: dict[str, Any] = {
        "success": True,
        "site": site,
        "filter_type": filter_type,
        "search": search,
        "fields": fields,
        "total_count": total_count,
        "returned_count": len(formatted_clients),
        "count": len(formatted_clients),
        "limit": limit,
        "clients": formatted_clients,
    }
    if unknown_fields:
        response["unknown_fields"] = unknown_fields
    return response


def shape_client_details(
    client: Any,
    *,
    site: str,
    mac_address: str,
    include: str = "basic",
    summary: bool = False,
) -> dict[str, Any]:
    """Shape full or section-selected client details."""
    if not client:
        return {"success": False, "error": f"Client not found with MAC address: {mac_address}"}
    raw = _raw(client)
    if not summary:
        shaped = client_from_controller(client).model_dump(exclude_none=True)
        merged: dict[str, Any] = dict(raw)
        for key in ("last_seen", "first_seen", "status", "name", "hostname"):
            if key in shaped:
                merged[key] = shaped[key]
        return {"success": True, "site": site, "client": merged}

    known_sections = {"basic", "network", "wireless", "traffic", "fingerprint", "all"}
    sections = {section.strip().lower() for section in include.split(",")}
    unknown_sections = sorted(sections - known_sections)
    include_all = "all" in sections
    client_data: dict[str, Any] = {}
    if include_all or "basic" in sections:
        client_data.update(
            {
                "mac": raw.get("mac"),
                "name": raw.get("name") or raw.get("hostname", "Unknown"),
                "hostname": raw.get("hostname"),
                "ip": raw.get("ip"),
                "connection_type": "Wired" if raw.get("is_wired", False) else "Wireless",
                "status": "Online" if _is_online(raw) else "Offline",
                "last_seen": raw.get("last_seen"),
                "uptime": raw.get("uptime"),
                "first_seen": raw.get("first_seen"),
            }
        )
    if include_all or "network" in sections:
        client_data.update(
            {
                "network_id": raw.get("network_id"),
                "network": raw.get("network"),
                "vlan": raw.get("vlan"),
                "use_fixedip": raw.get("use_fixedip", False),
                "fixed_ip": raw.get("fixed_ip"),
                "local_dns_record": raw.get("local_dns_record"),
            }
        )
    if (include_all or "wireless" in sections) and not raw.get("is_wired", False):
        client_data.update(
            {
                "essid": raw.get("essid"),
                "bssid": raw.get("bssid"),
                "channel": raw.get("channel"),
                "radio": raw.get("radio"),
                "radio_proto": raw.get("radio_proto"),
                "signal": raw.get("signal"),
                "rssi": raw.get("rssi"),
                "noise": raw.get("noise"),
                "satisfaction": raw.get("satisfaction"),
                "ap_mac": raw.get("ap_mac"),
            }
        )
    if include_all or "traffic" in sections:
        client_data.update(
            {
                "tx_bytes": raw.get("tx_bytes"),
                "rx_bytes": raw.get("rx_bytes"),
                "tx_packets": raw.get("tx_packets"),
                "rx_packets": raw.get("rx_packets"),
                "tx_rate": raw.get("tx_rate"),
                "rx_rate": raw.get("rx_rate"),
            }
        )
    if include_all or "fingerprint" in sections:
        client_data.update(
            {
                "oui": raw.get("oui"),
                "os_name": raw.get("os_name"),
                "dev_cat": raw.get("dev_cat"),
                "dev_family": raw.get("dev_family"),
                "dev_vendor": raw.get("dev_vendor"),
                "dev_id": raw.get("dev_id"),
                "fingerprint_source": raw.get("fingerprint_source"),
            }
        )
    response: dict[str, Any] = {
        "success": True,
        "site": site,
        "include": include,
        "summary_mode": True,
        "client": client_data,
    }
    if unknown_sections:
        response["unknown_sections"] = unknown_sections
    return response


def _device_base(device: dict[str, Any]) -> dict[str, Any]:
    state = device.get("state", 0)
    state_map = {
        0: "offline",
        1: "online",
        2: "pending_adoption",
        4: "managed_by_other/adopting",
        5: "provisioning",
        6: "upgrading",
        11: "error/heartbeat_missed",
    }
    sys_stats = device.get("sys_stats", {})
    mem_total = sys_stats.get("mem_total", 0)
    mem_used = sys_stats.get("mem_used", 0)
    uplink = device.get("uplink", device.get("last_uplink", {}))
    uplink_info = None
    if uplink:
        uplink_info = {
            "type": uplink.get("type", "unknown"),
            "speed": uplink.get("speed", 0),
            "uplink_device": uplink.get("uplink_device_name"),
            "uplink_port": uplink.get("uplink_remote_port"),
        }
    return {
        "mac": device.get("mac", ""),
        "name": device.get("name", device.get("model", "Unknown")),
        "model": device.get("model", ""),
        "type": device.get("type", ""),
        "device_category": classify_device(device),
        "ip": device.get("ip", ""),
        "status": state_map.get(state, f"unknown_state ({state})"),
        "uptime": str(timedelta(seconds=device.get("uptime", 0))) if device.get("uptime") else "N/A",
        "last_seen": datetime.fromtimestamp(device.get("last_seen", 0), tz=timezone.utc).isoformat()
        if device.get("last_seen")
        else "N/A",
        "firmware": device.get("version", ""),
        "upgradable": device.get("upgradable", False),
        "adopted": device.get("adopted", False),
        "connection_network": device.get("connection_network_name", ""),
        "uplink": uplink_info,
        "load_avg_1": sys_stats.get("loadavg_1"),
        "mem_pct": round((mem_used / mem_total) * 100, 1) if mem_total else None,
        "model_eol": device.get("model_in_eol", False),
        "_id": device.get("_id", ""),
    }


def _add_device_details(device: dict[str, Any], target: dict[str, Any], *, summary: bool) -> None:
    category = classify_device(device)
    target.update(
        {
            "serial": device.get("serial", ""),
            "hw_revision": device.get("hw_rev", ""),
            "model_display": device.get("model_display", device.get("model")),
            "clients": device.get("num_sta", 0),
        }
    )
    if summary and category == "ap":
        radio_table = device.get("radio_table", [])
        vap_table = device.get("vap_table", [])
        target.update(
            {
                "radio_count": len(radio_table),
                "radios": [
                    {"band": radio.get("radio"), "channel": radio.get("channel"), "tx_power": radio.get("tx_power")}
                    for radio in radio_table
                ],
                "vap_count": len(vap_table),
                "wifi_bands": get_wifi_bands(device),
                "experience_score": device.get("satisfaction", 0),
                "num_clients": device.get("num_sta", 0),
            }
        )
    elif summary and category == "switch":
        port_table = device.get("port_table", [])
        target.update(
            {
                "total_ports": len(port_table),
                "ports_up": sum(1 for port in port_table if port.get("up", False)),
                "ports_poe_enabled": sum(1 for port in port_table if port.get("poe_enable", False)),
                "num_clients": device.get("user-num_sta", 0) + device.get("guest-num_sta", 0),
                "poe_power": device.get("poe_power"),
                "poe_voltage": device.get("poe_voltage"),
            }
        )
    elif summary and category == "gateway":
        network_table = device.get("network_table", [])
        wan1 = device.get("wan1", {})
        wan2 = device.get("wan2", {})
        system_stats = device.get("system-stats", {})
        target.update(
            {
                "wan1_ip": wan1.get("ip") if wan1 else None,
                "wan1_up": wan1.get("up", False) if wan1 else None,
                "wan2_ip": wan2.get("ip") if wan2 else None,
                "wan2_up": wan2.get("up", False) if wan2 else None,
                "num_clients": device.get("user-num_sta", 0) + device.get("guest-num_sta", 0),
                "network_count": len(network_table),
                "cpu_usage": system_stats.get("cpu"),
                "mem_usage": system_stats.get("mem"),
            }
        )
    elif not summary and category == "ap":
        target.update(
            {
                "radio_table": device.get("radio_table", []),
                "vap_table": device.get("vap_table", []),
                "wifi_bands": get_wifi_bands(device),
                "experience_score": device.get("satisfaction", 0),
                "num_clients": device.get("num_sta", 0),
            }
        )
    elif not summary and category == "switch":
        port_table = device.get("port_table", [])
        target.update(
            {
                "ports": port_table,
                "total_ports": len(port_table),
                "num_clients": device.get("user-num_sta", 0) + device.get("guest-num_sta", 0),
                "poe_info": {
                    "poe_current": device.get("poe_current"),
                    "poe_power": device.get("poe_power"),
                    "poe_voltage": device.get("poe_voltage"),
                },
            }
        )
    elif not summary and category == "gateway":
        target.update(
            {
                "wan1": device.get("wan1", {}),
                "wan2": device.get("wan2", {}),
                "num_clients": device.get("user-num_sta", 0) + device.get("guest-num_sta", 0),
                "network_table": device.get("network_table", []),
                "system_stats": device.get("system-stats", {}),
                "speedtest_status": device.get("speedtest-status", {}),
            }
        )


def shape_device_list(
    devices: list[Any],
    *,
    site: str,
    device_type: str = "all",
    status: str = "all",
    search: str | None = None,
    limit: int | None = None,
    include_details: bool = False,
    summary: bool = True,
) -> dict[str, Any]:
    """Apply device inventory filters and compact/raw detail shaping."""
    devices_raw = [_raw(device) for device in devices]
    if device_type != "all":
        devices_raw = [device for device in devices_raw if classify_device(device) == device_type]
    if status != "all":
        state = {"online": 1, "offline": 0, "pending": 2, "adopting": 4, "provisioning": 5, "upgrading": 6}.get(status)
        if state is not None:
            devices_raw = [device for device in devices_raw if device.get("state") == state]
    if search and search.strip():
        search_lower = search.strip().lower()
        devices_raw = [
            device
            for device in devices_raw
            if search_lower in (device.get("name") or "").lower()
            or search_lower in (device.get("ip") or "").lower()
            or search_lower in (device.get("mac") or "").lower()
        ]
    total_count = len(devices_raw)
    if limit is not None:
        devices_raw = devices_raw[:limit]
    formatted = []
    for device in devices_raw:
        item = _device_base(device)
        if include_details:
            _add_device_details(device, item, summary=summary)
        formatted.append(item)
    return {
        "success": True,
        "site": site,
        "filter_type": device_type,
        "filter_status": status,
        "search": search,
        "total_count": total_count,
        "returned_count": len(formatted),
        "count": len(formatted),
        "limit": limit,
        "devices": formatted,
    }


def shape_device_details(
    device: Any,
    *,
    site: str,
    mac_address: str,
    include: str = "basic,ports",
    summary: bool = False,
) -> dict[str, Any]:
    """Shape full or section-selected device details."""
    if not device:
        return {"success": False, "error": f"Device not found with MAC address: {mac_address}"}
    raw = _raw(device)
    if not summary:
        return {"success": True, "site": site, "include": "all", "summary_mode": False, "device": raw}
    known_sections = {"basic", "ports", "radios", "stats", "uplink", "lldp", "all"}
    sections = {section.strip().lower() for section in include.split(",")}
    unknown_sections = sorted(sections - known_sections)
    include_all = "all" in sections
    data: dict[str, Any] = {}
    if include_all or "basic" in sections:
        state = raw.get("state", 0)
        state_map = {
            0: "offline",
            1: "online",
            2: "pending_adoption",
            4: "managed_by_other/adopting",
            5: "provisioning",
            6: "upgrading",
            11: "error/heartbeat_missed",
        }
        data.update(
            {
                "mac": raw.get("mac"),
                "name": raw.get("name", raw.get("model", "Unknown")),
                "model": raw.get("model"),
                "type": raw.get("type"),
                "ip": raw.get("ip"),
                "status": state_map.get(state, f"unknown ({state})"),
                "uptime": str(timedelta(seconds=raw.get("uptime", 0))) if raw.get("uptime") else None,
                "firmware": raw.get("version"),
                "adopted": raw.get("adopted", False),
            }
        )
    if (include_all or "ports" in sections) and "port_table" in raw:
        lldp_by_port = {
            entry["local_port_idx"]: {
                "mac": entry.get("chassis_id"),
                "name": entry.get("chassis_name"),
                "port": entry.get("port_id"),
            }
            for entry in raw.get("lldp_table", [])
            if entry.get("local_port_idx") is not None
        }
        data["port_summary"] = [
            {
                "port_idx": port.get("port_idx"),
                "name": port.get("name"),
                "up": port.get("up"),
                "speed": port.get("speed"),
                "poe_enable": port.get("poe_enable"),
                "poe_power": port.get("poe_power"),
                "last_seen_mac": port.get("last_connection", {}).get("mac"),
                "lldp_neighbor": lldp_by_port.get(port.get("port_idx")),
            }
            for port in raw["port_table"]
        ]
        data["port_count"] = len(raw["port_table"])
    if (include_all or "radios" in sections) and "radio_table" in raw:
        data["radio_summary"] = [
            {
                "radio": radio.get("radio"),
                "channel": normalize_radio_channel(radio.get("channel")),
                "tx_power": radio.get("tx_power"),
            }
            for radio in raw["radio_table"]
        ]
        data["radio_count"] = len(raw["radio_table"])
        if "vap_table" in raw:
            data["vap_count"] = len(raw["vap_table"])
    if (include_all or "stats" in sections) and "system-stats" in raw:
        data["system_stats"] = raw["system-stats"]
    if (include_all or "uplink" in sections) and "uplink" in raw:
        uplink = raw["uplink"]
        data["uplink"] = {
            "type": uplink.get("type"),
            "uplink_mac": uplink.get("uplink_mac"),
            "uplink_device_name": uplink.get("uplink_device_name"),
            "uplink_remote_port": uplink.get("uplink_remote_port"),
            "speed": uplink.get("speed"),
            "ip": uplink.get("ip"),
        }
    if (include_all or "lldp" in sections) and "lldp_table" in raw:
        data["lldp_table"] = raw["lldp_table"]
    response: dict[str, Any] = {
        "success": True,
        "site": site,
        "include": include,
        "summary_mode": True,
        "device": data,
    }
    if unknown_sections:
        response["unknown_sections"] = unknown_sections
    return response


def shape_network_list(
    networks: list[dict[str, Any]],
    *,
    site: str,
    search: str | None = None,
    purpose: str | None = None,
    limit: int = 25,
    fields: str | None = None,
) -> dict[str, Any]:
    """Apply network filters and field projection."""
    filtered = list(networks)
    if purpose and purpose.strip():
        filtered = [network for network in filtered if network.get("purpose") == purpose.strip().lower()]
    if search and search.strip():
        search_lower = search.strip().lower()
        filtered = [
            network
            for network in filtered
            if search_lower in (network.get("name") or "").lower() or search_lower == str(network.get("vlan") or "")
        ]
    total_count = len(filtered)
    filtered = filtered[:limit]
    known_fields = {
        "_id",
        "name",
        "enabled",
        "purpose",
        "ip_subnet",
        "vlan_enabled",
        "vlan",
        "dhcpd_enabled",
        "dhcpd_start",
        "dhcpd_stop",
    }
    requested_fields: set[str] | None = None
    unknown_fields: list[str] = []
    if fields and fields.strip():
        requested_fields = {field.strip() for field in fields.split(",")}
        unknown_fields = sorted(requested_fields - known_fields)
    formatted = []
    for network in filtered:
        shaped = network_from_controller(network)
        full_data = {
            "_id": shaped.id,
            "name": shaped.name,
            "enabled": shaped.enabled,
            "purpose": shaped.purpose,
            "ip_subnet": shaped.ip_subnet,
            "vlan_enabled": shaped.vlan_enabled,
            "vlan": shaped.vlan,
            "dhcpd_enabled": shaped.dhcpd_enabled,
            "dhcpd_start": shaped.dhcpd_start,
            "dhcpd_stop": shaped.dhcpd_stop,
        }
        formatted.append(
            {key: value for key, value in full_data.items() if key in requested_fields}
            if requested_fields
            else full_data
        )
    response: dict[str, Any] = {
        "success": True,
        "site": site,
        "search": search,
        "purpose_filter": purpose,
        "fields": fields,
        "total_count": total_count,
        "returned_count": len(formatted),
        "count": len(formatted),
        "limit": limit,
        "networks": formatted,
    }
    if unknown_fields:
        response["unknown_fields"] = unknown_fields
    return response


def shape_network_details(
    network: dict[str, Any] | None,
    *,
    site: str,
    network_id: str,
    include: str = "basic",
    summary: bool = False,
) -> dict[str, Any]:
    """Shape full or section-selected network details."""
    if not network:
        return {"success": False, "error": f"Network with ID '{network_id}' not found."}
    if not summary:
        return {
            "success": True,
            "site": site,
            "network_id": network_id,
            "include": "all",
            "summary_mode": False,
            "details": json.loads(json.dumps(network, default=str)),
        }
    known_sections = {"basic", "dhcp", "ipv6", "vpn", "wan", "all"}
    sections = {section.strip().lower() for section in include.split(",")}
    unknown_sections = sorted(sections - known_sections)
    include_all = "all" in sections
    data: dict[str, Any] = {}
    if include_all or "basic" in sections:
        data.update(
            {
                "_id": network.get("_id"),
                "name": network.get("name"),
                "enabled": network.get("enabled"),
                "purpose": network.get("purpose"),
                "ip_subnet": network.get("ip_subnet"),
                "vlan_enabled": network.get("vlan_enabled"),
                "vlan": network.get("vlan"),
                "domain_name": network.get("domain_name"),
                "is_nat": network.get("is_nat"),
                "network_isolation_enabled": network.get("network_isolation_enabled"),
            }
        )
    if include_all or "dhcp" in sections:
        for key in (
            "dhcpd_enabled",
            "dhcpd_start",
            "dhcpd_stop",
            "dhcpd_leasetime",
            "dhcpd_dns_enabled",
            "dhcpd_gateway_enabled",
            "dhcpd_unifi_controller",
        ):
            data[key] = network.get(key)
    if include_all or "ipv6" in sections:
        for key in (
            "ipv6_interface_type",
            "ipv6_aliases",
            "ipv6_pd_interface",
            "ipv6_pd_prefixid",
            "ipv6_pd_auto_prefixid_enabled",
            "ipv6_pd_start",
            "ipv6_pd_stop",
            "ipv6_ra_enabled",
            "ipv6_ra_priority",
            "ipv6_ra_preferred_lifetime",
            "ipv6_client_address_assignment",
            "dhcpdv6_enabled",
            "dhcpdv6_allow_slaac",
            "dhcpdv6_dns_auto",
            "dhcpdv6_leasetime",
            "dhcpdv6_start",
            "dhcpdv6_stop",
        ):
            data[key] = network.get(key)
    if include_all or "vpn" in sections:
        for key in ("vpn_type", "remote_site_id", "remote_site_subnets"):
            data[key] = network.get(key)
    if include_all or "wan" in sections:
        for key in (
            "wan_networkgroup",
            "wan_type",
            "wan_dns_preference",
            "wan_load_balance_type",
            "wan_load_balance_weight",
            "wan_failover_priority",
            "wan_smartq_enabled",
            "wan_vlan_enabled",
            "igmp_proxy_upstream",
            "igmp_proxy_for",
            "mac_override_enabled",
            "wan_ip_aliases",
            "ipv6_enabled",
            "wan_type_v6",
            "ipv6_setting_preference",
            "ipv6_wan_delegation_type",
            "wan_dhcpv6_pd_size",
            "wan_dhcpv6_pd_size_auto",
            "wan_ipv6_dns_preference",
            "wan_ipv6_dns1",
            "wan_ipv6_dns2",
        ):
            data[key] = network.get(key)
    response: dict[str, Any] = {
        "success": True,
        "site": site,
        "network_id": network_id,
        "include": include,
        "summary_mode": True,
        "details": data,
    }
    if unknown_sections:
        response["unknown_sections"] = unknown_sections
    return response


def shape_wlan_list(
    wlans: list[Any],
    *,
    site: str,
    search: str | None = None,
    enabled_only: bool = False,
    limit: int = 25,
) -> dict[str, Any]:
    """Apply WLAN filters and public list projection."""
    raw = [_raw(wlan) for wlan in wlans]
    if enabled_only:
        raw = [wlan for wlan in raw if wlan.get("enabled", False)]
    if search and search.strip():
        search_lower = search.strip().lower()
        raw = [wlan for wlan in raw if search_lower in (wlan.get("name") or "").lower()]
    total_count = len(raw)
    raw = raw[:limit]
    formatted = [
        {
            "id": wlan.get("_id"),
            "name": wlan.get("name"),
            "enabled": wlan.get("enabled"),
            "security": wlan.get("security"),
            "network_id": wlan.get("networkconf_id"),
            "usergroup_id": wlan.get("usergroup_id"),
        }
        for wlan in raw
    ]
    return {
        "success": True,
        "site": site,
        "search": search,
        "enabled_only": enabled_only,
        "total_count": total_count,
        "returned_count": len(formatted),
        "count": len(formatted),
        "limit": limit,
        "wlans": formatted,
    }


# selector -> (activating enum key, value); a selector under any other value is not shown.
_SELECTOR_ACTIVATION = {selector: (key, value) for selector, key, value in SELECTOR_ACTIVATORS}
_FIREWALL_TARGETING_KEYS = (
    "matching_target_type",
    "ips",
    "ip_group_id",
    "network_ids",
    "client_macs",
    "port",
    "port_group_id",
    "match_opposite_ips",
    "match_opposite_networks",
    "match_opposite_ports",
)


def shape_firewall_policy_list(
    policies: list[Any],
    *,
    site: str,
    search: str | None = None,
    action: str | None = None,
    enabled_only: bool = False,
    limit: int = 50,
    summary: bool = True,
) -> dict[str, Any]:
    """Apply firewall policy filters and curated/full projection."""
    raw = [_raw(policy) for policy in policies]
    controller_policy_count = len(raw)
    if enabled_only:
        raw = [policy for policy in raw if policy.get("enabled", False)]
    if action and action.strip():
        raw = [policy for policy in raw if policy.get("action") == action.strip().upper()]
    if search and search.strip():
        search_lower = search.strip().lower()
        raw = [policy for policy in raw if search_lower in (policy.get("name") or "").lower()]
    total_count = len(raw)
    raw = raw[:limit]
    formatted = []
    for policy in raw:
        shaped = firewall_policy_from_controller(policy)
        if not summary:
            formatted.append(shaped.model_dump(exclude_none=True))
            continue
        entry = {
            "id": shaped.id,
            "name": shaped.name,
            "enabled": shaped.enabled,
            "action": shaped.action,
            "rule_index": shaped.index,
            "description": policy.get("description", policy.get("desc", "")),
        }
        if shaped.protocol:
            entry["protocol"] = shaped.protocol
        for direction in ("source", "destination"):
            endpoint = getattr(shaped, direction)
            if endpoint and isinstance(endpoint, dict):
                targeting = {"zone_id": endpoint.get("zone_id"), "matching_target": endpoint.get("matching_target")}
                port_matching_type = endpoint.get("port_matching_type")
                if port_matching_type and port_matching_type != "ANY":
                    targeting["port_matching_type"] = port_matching_type
                # Selectors and inversion flags, in display order; only set (truthy) values are shown,
                # and a port selector only under the port_matching_type that activates it.
                for key in _FIREWALL_TARGETING_KEYS:
                    activator = _SELECTOR_ACTIVATION.get(key)
                    if activator and endpoint.get(activator[0]) != activator[1]:
                        continue
                    if endpoint.get(key):
                        targeting[key] = endpoint[key]
                entry[direction] = targeting
        formatted.append(entry)
    response = {
        "success": True,
        "site": site,
        "search": search,
        "action_filter": action,
        "enabled_only": enabled_only,
        "total_count": total_count,
        "returned_count": len(formatted),
        "count": len(formatted),
        "limit": limit,
        "policies": formatted,
    }
    if controller_policy_count == 0:
        response["note"] = LEGACY_ENGINE_HINT
    return response


def _rogue_ap_summary(ap: dict[str, Any]) -> dict[str, Any]:
    return {
        "bssid": ap.get("bssid"),
        "ssid": ap.get("essid"),
        "channel": ap.get("channel"),
        "signal": ap.get("signal"),
        "rssi": ap.get("rssi"),
        "band": ap.get("band"),
        "bandwidth": ap.get("bw"),
        "security": ap.get("security"),
        "ap_mac": ap.get("ap_mac"),
        "ap_name": ap.get("ap_name"),
        "last_seen": ap.get("last_seen"),
        "is_rogue": ap.get("is_rogue"),
    }


def shape_rogue_ap_list(
    rogue_aps: list[dict[str, Any]],
    *,
    site: str,
    within_hours: int = 24,
    channel: int | None = None,
    min_signal: int | None = None,
    limit: int = 100,
    offset: int = 0,
    summary: bool = True,
) -> dict[str, Any]:
    """Apply rogue-AP filters, pagination, and compact/raw projection."""
    filtered = list(rogue_aps)
    if channel is not None:
        filtered = [ap for ap in filtered if ap.get("channel") == channel]
    if min_signal is not None:
        filtered = [ap for ap in filtered if ap.get("signal", -100) >= min_signal]
    total_count = len(filtered)
    page = filtered[offset : offset + limit]
    formatted = [_rogue_ap_summary(ap) for ap in page] if summary else page
    next_offset = offset + len(page) if offset + len(page) < total_count else None
    return {
        "success": True,
        "site": site,
        "within_hours": within_hours,
        "filters": {"channel": channel, "min_signal": min_signal},
        "summary_mode": summary,
        "total_count": total_count,
        "returned_count": len(formatted),
        "count": len(formatted),
        "limit": limit,
        "offset": offset,
        "next_offset": next_offset,
        "has_more": next_offset is not None,
        "rogue_aps": formatted,
    }


def shape_alerts(
    alerts: list[dict[str, Any]],
    *,
    site: str,
    limit: int = 10,
    include_archived: bool = False,
) -> dict[str, Any]:
    """Apply the public alert limit and response envelope."""
    return {
        "success": True,
        "site": site,
        "limit": limit,
        "include_archived": include_archived,
        "alerts": alerts[:limit],
    }


def shape_dashboard(
    dashboard: list[dict[str, Any]],
    *,
    site: str,
    summary: bool = True,
    history_seconds: int = 86400,
) -> dict[str, Any]:
    """Apply dashboard time-series compression and response metadata."""
    omitted = (
        sorted({key for entry in dashboard for key in _DASHBOARD_TIMESERIES_SECTIONS if key in entry})
        if summary
        else []
    )
    formatted = (
        [
            {key: value for key, value in entry.items() if key not in _DASHBOARD_TIMESERIES_SECTIONS}
            for entry in dashboard
        ]
        if summary
        else dashboard
    )
    return {
        "success": True,
        "site": site,
        "summary_mode": summary,
        "history_seconds": history_seconds,
        "omitted_sections": omitted,
        "dashboard": formatted,
    }
