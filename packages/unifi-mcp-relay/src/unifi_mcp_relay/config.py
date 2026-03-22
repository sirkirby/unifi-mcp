"""Configuration loading from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RelayConfig:
    """MCP relay configuration."""

    relay_url: str
    relay_token: str
    location_name: str
    servers: list[str] = field(default_factory=lambda: ["http://localhost:3000"])
    refresh_interval: int = 300
    reconnect_max_delay: int = 60


def load_config() -> RelayConfig:
    """Load config from environment variables. Raises ValueError for missing required vars."""
    relay_url = os.environ.get("UNIFI_RELAY_URL", "")
    relay_token = os.environ.get("UNIFI_RELAY_TOKEN", "")
    location_name = os.environ.get("UNIFI_RELAY_LOCATION_NAME", "")

    missing = []
    if not relay_url:
        missing.append("UNIFI_RELAY_URL")
    if not relay_token:
        missing.append("UNIFI_RELAY_TOKEN")
    if not location_name:
        missing.append("UNIFI_RELAY_LOCATION_NAME")
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    servers_raw = os.environ.get("UNIFI_RELAY_SERVERS", "http://localhost:3000")
    servers = [s.strip() for s in servers_raw.split(",") if s.strip()]
    refresh_interval = int(os.environ.get("UNIFI_RELAY_REFRESH_INTERVAL", "300"))
    reconnect_max_delay = int(os.environ.get("UNIFI_RELAY_RECONNECT_MAX_DELAY", "60"))

    return RelayConfig(
        relay_url=relay_url,
        relay_token=relay_token,
        location_name=location_name,
        servers=servers,
        refresh_interval=refresh_interval,
        reconnect_max_delay=reconnect_max_delay,
    )
