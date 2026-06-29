"""Shared field model for gateway (USG) settings.

Mirrors the Strawberry type in
``unifi_api.graphql.types.network.gateway_settings`` (class ``GatewaySettings``).

The controller exposes these as a single per-site settings object under the
``usg`` key: GET ``/get/setting/usg`` -> PUT ``/set/setting/usg``. Unlike the
collection-style network configs there is no per-item identifier to target --
it is a singleton, so there is no create payload, only a partial update that is
deep-merged onto the current object.

Factory helpers:
- ``from_controller``      -- normalise the raw controller dict -> GatewaySettings
- ``to_controller_update`` -- filter a partial dict to mutable keys only

``MUTABLE_FIELDS`` drives the cross-layer symmetry test: the Strawberry type
must expose every field listed here.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator


class GatewaySettings(BaseModel):
    """Canonical gateway (USG) settings model (read + mutable fields)."""

    # --- read-only identity ---
    id: Optional[str] = Field(
        default=None,
        description="Settings object UUID (assigned by controller)",
        json_schema_extra={"mutable": False},
    )
    site_id: Optional[str] = Field(
        default=None,
        description="Site ID these settings belong to",
        json_schema_extra={"mutable": False},
    )
    key: Optional[str] = Field(
        default=None,
        description="Settings section key (always 'usg')",
        json_schema_extra={"mutable": False},
    )

    # --- Security ---
    geo_ip_filtering_enabled: Optional[bool] = Field(default=None, description="Enable GeoIP firewall filtering.")
    geo_ip_filtering_block: Optional[str] = Field(
        default=None,
        description="GeoIP mode: 'block' (blocklist) or 'allow' (allowlist) the listed countries.",
    )
    geo_ip_filtering_countries: Optional[str] = Field(
        default=None, description="Comma-separated ISO country codes for the GeoIP list."
    )
    geo_ip_filtering_traffic_direction: Optional[str] = Field(
        default=None, description="GeoIP direction: 'both', 'ingress', or 'egress'."
    )
    syn_cookies: Optional[bool] = Field(default=None, description="Enable SYN-cookie flood protection.")
    broadcast_ping: Optional[bool] = Field(default=None, description="Respond to broadcast ICMP echo (ping).")
    receive_redirects: Optional[bool] = Field(default=None, description="Accept ICMP redirects.")
    send_redirects: Optional[bool] = Field(default=None, description="Send ICMP redirects.")
    dns_verification: Optional[Any] = Field(
        default=None,
        description=(
            "Nested DNS-verification object {setting_preference, primary_dns_server, secondary_dns_server, domain}."
        ),
    )

    # --- NAT / UPnP ---
    upnp_enabled: Optional[bool] = Field(default=None, description="Enable UPnP.")
    upnp_nat_pmp_enabled: Optional[bool] = Field(default=None, description="Enable NAT-PMP (alongside UPnP).")
    upnp_secure_mode: Optional[bool] = Field(
        default=None,
        description="UPnP secure mode (only allow port maps to the requesting host).",
    )
    upnp_wan_interface: Optional[str] = Field(
        default=None, description="WAN interface UPnP listens on (e.g. 'WAN', 'WAN2')."
    )
    mss_clamp: Optional[str] = Field(
        default=None, description="TCP MSS clamping mode (e.g. 'auto', 'custom', 'disabled')."
    )

    # --- Connection-tracking helper (ALG) modules ---
    ftp_module: Optional[bool] = Field(default=None, description="Enable the FTP conntrack helper module.")
    gre_module: Optional[bool] = Field(default=None, description="Enable the GRE conntrack helper module.")
    h323_module: Optional[bool] = Field(default=None, description="Enable the H.323 conntrack helper module.")
    pptp_module: Optional[bool] = Field(default=None, description="Enable the PPTP conntrack helper module.")
    sip_module: Optional[bool] = Field(default=None, description="Enable the SIP conntrack helper module.")
    tftp_module: Optional[bool] = Field(default=None, description="Enable the TFTP conntrack helper module.")

    # --- Hardware offloading ---
    offload_accounting: Optional[bool] = Field(default=None, description="Enable offload accounting.")
    offload_l2_blocking: Optional[bool] = Field(default=None, description="Enable offload L2 blocking.")
    offload_sch: Optional[bool] = Field(default=None, description="Enable offload scheduler (flow offloading).")

    # --- Conntrack timeouts (seconds) ---
    icmp_timeout: Optional[int] = Field(default=None, description="ICMP conntrack timeout (seconds).")
    other_timeout: Optional[int] = Field(default=None, description="Other-protocol conntrack timeout (seconds).")
    udp_stream_timeout: Optional[int] = Field(
        default=None, description="UDP stream (assured) conntrack timeout (seconds)."
    )
    udp_other_timeout: Optional[int] = Field(default=None, description="UDP other conntrack timeout (seconds).")
    tcp_established_timeout: Optional[int] = Field(
        default=None, description="TCP established conntrack timeout (seconds)."
    )
    tcp_close_timeout: Optional[int] = Field(default=None, description="TCP close conntrack timeout (seconds).")
    tcp_close_wait_timeout: Optional[int] = Field(
        default=None, description="TCP close-wait conntrack timeout (seconds)."
    )
    tcp_fin_wait_timeout: Optional[int] = Field(default=None, description="TCP fin-wait conntrack timeout (seconds).")
    tcp_last_ack_timeout: Optional[int] = Field(default=None, description="TCP last-ack conntrack timeout (seconds).")
    tcp_syn_recv_timeout: Optional[int] = Field(default=None, description="TCP syn-recv conntrack timeout (seconds).")
    tcp_syn_sent_timeout: Optional[int] = Field(default=None, description="TCP syn-sent conntrack timeout (seconds).")
    tcp_time_wait_timeout: Optional[int] = Field(default=None, description="TCP time-wait conntrack timeout (seconds).")
    timeout_setting_preference: Optional[str] = Field(
        default=None, description="Conntrack-timeout source: 'auto' or 'manual'."
    )

    # --- Misc ---
    unbind_wan_monitors: Optional[bool] = Field(default=None, description="Unbind WAN uplink monitors.")

    @field_validator("geo_ip_filtering_countries", mode="before")
    @classmethod
    def _normalize_countries(cls, value: Any) -> Any:
        """Coerce the GeoIP country list to the canonical CSV string.

        Some controller firmware returns ``geo_ip_filtering_countries`` as a JSON
        array (e.g. ``["US", "CA"]``) rather than a comma-separated string. Without
        this, a populated GeoIP config would fail ``str`` validation and break the
        read path. The model's canonical shape stays CSV (matching the Strawberry
        type and the tool description).
        """
        if isinstance(value, (list, tuple)):
            return ",".join(str(item) for item in value)
        return value


# ---------------------------------------------------------------------------
# Field sets
# ---------------------------------------------------------------------------

MUTABLE_FIELDS: frozenset[str] = frozenset(
    name for name, field in GatewaySettings.model_fields.items() if (field.json_schema_extra or {}).get("mutable", True)
)

READ_ONLY_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in GatewaySettings.model_fields.items()
    if (field.json_schema_extra or {}).get("mutable", True) is False
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# ---------------------------------------------------------------------------
# Public factory helpers
# ---------------------------------------------------------------------------


def from_controller(raw: Any) -> GatewaySettings:
    """Build a GatewaySettings from a controller API response dict."""
    return GatewaySettings(
        id=_get(raw, "_id") or _get(raw, "id"),
        site_id=_get(raw, "site_id"),
        key=_get(raw, "key"),
        geo_ip_filtering_enabled=_get(raw, "geo_ip_filtering_enabled"),
        geo_ip_filtering_block=_get(raw, "geo_ip_filtering_block"),
        geo_ip_filtering_countries=_get(raw, "geo_ip_filtering_countries"),
        geo_ip_filtering_traffic_direction=_get(raw, "geo_ip_filtering_traffic_direction"),
        syn_cookies=_get(raw, "syn_cookies"),
        broadcast_ping=_get(raw, "broadcast_ping"),
        receive_redirects=_get(raw, "receive_redirects"),
        send_redirects=_get(raw, "send_redirects"),
        dns_verification=_get(raw, "dns_verification"),
        upnp_enabled=_get(raw, "upnp_enabled"),
        upnp_nat_pmp_enabled=_get(raw, "upnp_nat_pmp_enabled"),
        upnp_secure_mode=_get(raw, "upnp_secure_mode"),
        upnp_wan_interface=_get(raw, "upnp_wan_interface"),
        mss_clamp=_get(raw, "mss_clamp"),
        ftp_module=_get(raw, "ftp_module"),
        gre_module=_get(raw, "gre_module"),
        h323_module=_get(raw, "h323_module"),
        pptp_module=_get(raw, "pptp_module"),
        sip_module=_get(raw, "sip_module"),
        tftp_module=_get(raw, "tftp_module"),
        offload_accounting=_get(raw, "offload_accounting"),
        offload_l2_blocking=_get(raw, "offload_l2_blocking"),
        offload_sch=_get(raw, "offload_sch"),
        icmp_timeout=_get(raw, "icmp_timeout"),
        other_timeout=_get(raw, "other_timeout"),
        udp_stream_timeout=_get(raw, "udp_stream_timeout"),
        udp_other_timeout=_get(raw, "udp_other_timeout"),
        tcp_established_timeout=_get(raw, "tcp_established_timeout"),
        tcp_close_timeout=_get(raw, "tcp_close_timeout"),
        tcp_close_wait_timeout=_get(raw, "tcp_close_wait_timeout"),
        tcp_fin_wait_timeout=_get(raw, "tcp_fin_wait_timeout"),
        tcp_last_ack_timeout=_get(raw, "tcp_last_ack_timeout"),
        tcp_syn_recv_timeout=_get(raw, "tcp_syn_recv_timeout"),
        tcp_syn_sent_timeout=_get(raw, "tcp_syn_sent_timeout"),
        tcp_time_wait_timeout=_get(raw, "tcp_time_wait_timeout"),
        timeout_setting_preference=_get(raw, "timeout_setting_preference"),
        unbind_wan_monitors=_get(raw, "unbind_wan_monitors"),
    )


def to_controller_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a partial dict to only mutable, recognised keys.

    Read-only fields and unrecognised keys are dropped.
    ``None`` values are dropped; boolean ``False`` is preserved.
    """
    return {k: v for k, v in fields.items() if k in MUTABLE_FIELDS and v is not None}
