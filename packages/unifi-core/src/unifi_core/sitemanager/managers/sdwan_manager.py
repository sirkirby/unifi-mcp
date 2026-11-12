"""SD-WAN configurations from the Site Manager API."""

from __future__ import annotations

from unifi_core.exceptions import UniFiMalformedResponseError
from unifi_core.sitemanager.managers.connection_manager import SiteManagerConnectionManager, path_segment
from unifi_core.sitemanager.models.sdwan import (
    SdwanConfig,
    SdwanConfigStatus,
    SdwanConfigSummary,
    sdwan_config_from_api,
    sdwan_status_from_api,
    sdwan_summary_from_api,
)


class SdwanManager:
    """Reads SD-WAN configurations and their deployment status."""

    def __init__(self, connection: SiteManagerConnectionManager) -> None:
        self._connection = connection

    async def list_configs(self) -> list[SdwanConfigSummary]:
        response = await self._connection.get("/v1/sd-wan-configs")
        if not isinstance(response.data, list):
            raise UniFiMalformedResponseError("Site Manager API returned an unreadable SD-WAN configuration list.")
        return [sdwan_summary_from_api(entry) for entry in response.data]

    async def get_config(self, config_id: str) -> SdwanConfig:
        response = await self._connection.get(
            f"/v1/sd-wan-configs/{path_segment(config_id, 'SD-WAN configuration')}",
            resource=("SD-WAN configuration", config_id),
        )
        if not isinstance(response.data, dict):
            raise UniFiMalformedResponseError("Site Manager API returned an unreadable SD-WAN configuration.")
        return sdwan_config_from_api(response.data)

    async def get_config_status(self, config_id: str) -> SdwanConfigStatus:
        response = await self._connection.get(
            f"/v1/sd-wan-configs/{path_segment(config_id, 'SD-WAN configuration')}/status",
            resource=("SD-WAN configuration", config_id),
        )
        if not isinstance(response.data, dict):
            raise UniFiMalformedResponseError("Site Manager API returned an unreadable SD-WAN status.")
        return sdwan_status_from_api(response.data)
