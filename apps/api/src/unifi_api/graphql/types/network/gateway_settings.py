"""Strawberry type for network/gateway_settings (the USG settings singleton).

Mirrors the shared pydantic model in
``unifi_core.network.models.gateway_settings`` (class ``GatewaySettings``).

``from_manager_output(raw)`` shapes the controller settings dict; ``to_dict()``
exposes the same dict contract the REST route returns.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import strawberry


@strawberry.type(description="UniFi gateway (USG) security / NAT / connection-tracking settings.")
class GatewaySettings:
    id: strawberry.ID | None
    key: str | None
    # Security
    geo_ip_filtering_enabled: bool | None
    geo_ip_filtering_block: str | None
    geo_ip_filtering_countries: str | None
    geo_ip_filtering_traffic_direction: str | None
    syn_cookies: bool | None
    broadcast_ping: bool | None
    receive_redirects: bool | None
    send_redirects: bool | None
    dns_verification: strawberry.scalars.JSON | None  # type: ignore[name-defined]
    # NAT / UPnP
    upnp_enabled: bool | None
    upnp_nat_pmp_enabled: bool | None
    upnp_secure_mode: bool | None
    upnp_wan_interface: str | None
    mss_clamp: str | None
    # Connection-tracking helper (ALG) modules
    ftp_module: bool | None
    gre_module: bool | None
    h323_module: bool | None
    pptp_module: bool | None
    sip_module: bool | None
    tftp_module: bool | None
    # Hardware offloading
    offload_accounting: bool | None
    offload_l2_blocking: bool | None
    offload_sch: bool | None
    # Conntrack timeouts (seconds)
    icmp_timeout: int | None
    other_timeout: int | None
    udp_stream_timeout: int | None
    udp_other_timeout: int | None
    tcp_established_timeout: int | None
    tcp_close_timeout: int | None
    tcp_close_wait_timeout: int | None
    tcp_fin_wait_timeout: int | None
    tcp_last_ack_timeout: int | None
    tcp_syn_recv_timeout: int | None
    tcp_syn_sent_timeout: int | None
    tcp_time_wait_timeout: int | None
    timeout_setting_preference: str | None
    # Misc
    unbind_wan_monitors: bool | None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["key"],
            "sort_default": "key:asc",
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "GatewaySettings":
        raw = getattr(obj, "raw", obj if isinstance(obj, dict) else {})
        # Some firmware returns geo_ip_filtering_countries as an array; the GraphQL
        # field is a CSV string. Normalize so a populated GeoIP config serializes.
        countries = raw.get("geo_ip_filtering_countries")
        if isinstance(countries, (list, tuple)):
            countries = ",".join(str(item) for item in countries)
        return cls(
            id=raw.get("_id") or raw.get("id"),
            key=raw.get("key"),
            geo_ip_filtering_enabled=raw.get("geo_ip_filtering_enabled"),
            geo_ip_filtering_block=raw.get("geo_ip_filtering_block"),
            geo_ip_filtering_countries=countries,
            geo_ip_filtering_traffic_direction=raw.get("geo_ip_filtering_traffic_direction"),
            syn_cookies=raw.get("syn_cookies"),
            broadcast_ping=raw.get("broadcast_ping"),
            receive_redirects=raw.get("receive_redirects"),
            send_redirects=raw.get("send_redirects"),
            dns_verification=raw.get("dns_verification"),
            upnp_enabled=raw.get("upnp_enabled"),
            upnp_nat_pmp_enabled=raw.get("upnp_nat_pmp_enabled"),
            upnp_secure_mode=raw.get("upnp_secure_mode"),
            upnp_wan_interface=raw.get("upnp_wan_interface"),
            mss_clamp=raw.get("mss_clamp"),
            ftp_module=raw.get("ftp_module"),
            gre_module=raw.get("gre_module"),
            h323_module=raw.get("h323_module"),
            pptp_module=raw.get("pptp_module"),
            sip_module=raw.get("sip_module"),
            tftp_module=raw.get("tftp_module"),
            offload_accounting=raw.get("offload_accounting"),
            offload_l2_blocking=raw.get("offload_l2_blocking"),
            offload_sch=raw.get("offload_sch"),
            icmp_timeout=raw.get("icmp_timeout"),
            other_timeout=raw.get("other_timeout"),
            udp_stream_timeout=raw.get("udp_stream_timeout"),
            udp_other_timeout=raw.get("udp_other_timeout"),
            tcp_established_timeout=raw.get("tcp_established_timeout"),
            tcp_close_timeout=raw.get("tcp_close_timeout"),
            tcp_close_wait_timeout=raw.get("tcp_close_wait_timeout"),
            tcp_fin_wait_timeout=raw.get("tcp_fin_wait_timeout"),
            tcp_last_ack_timeout=raw.get("tcp_last_ack_timeout"),
            tcp_syn_recv_timeout=raw.get("tcp_syn_recv_timeout"),
            tcp_syn_sent_timeout=raw.get("tcp_syn_sent_timeout"),
            tcp_time_wait_timeout=raw.get("tcp_time_wait_timeout"),
            timeout_setting_preference=raw.get("timeout_setting_preference"),
            unbind_wan_monitors=raw.get("unbind_wan_monitors"),
        )

    def to_dict(self) -> dict:
        out = asdict(self)
        return {k: v for k, v in out.items() if not k.startswith("_") and not callable(v)}
