"""InnerSpace application status, read from the console's system endpoint."""

from __future__ import annotations

from unifi_core.innerspace.managers.connection_manager import (
    SYSTEM_PATH,
    InnerSpaceConnectionManager,
    reconnects_on_demand,
)
from unifi_core.innerspace.models.status import InnerSpaceAppStatus, app_status_from_api


@reconnects_on_demand
class InnerSpaceSystemManager:
    def __init__(self, cm: InnerSpaceConnectionManager) -> None:
        self._cm = cm

    async def get_status(self) -> InnerSpaceAppStatus:
        """Whether InnerSpace is installed and running, with its version and any update."""
        raw = await self._cm.request("GET", SYSTEM_PATH, operation="get InnerSpace status")
        return app_status_from_api(raw)
