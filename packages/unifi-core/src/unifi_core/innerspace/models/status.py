"""InnerSpace app status, read from the console's system endpoint."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from unifi_core.innerspace.models._coerce import as_dict, as_list, text

_APP_NAME = "innerspace"


class InnerSpaceAppStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")

    installed: bool = Field(description="Whether the InnerSpace application is installed")
    running: bool = Field(description="Whether the InnerSpace application is running")
    version: str | None = Field(default=None, description="Installed version")
    update_available: str | None = Field(default=None, description="Version available as an update, if any")


def app_status_from_api(raw: Any) -> InnerSpaceAppStatus:
    """Build the status from the ``/api/system`` payload; an absent entry means not installed."""
    controllers = as_list(as_dict(as_dict(raw).get("apps")).get("controllers"))
    entry = next((c for c in controllers if as_dict(c).get("name") == _APP_NAME), None)
    if entry is None:
        return InnerSpaceAppStatus(installed=False, running=False)
    return InnerSpaceAppStatus(
        installed=entry.get("isInstalled") is True,
        running=entry.get("isRunning") is True,
        version=text(entry.get("version")),
        update_available=text(entry.get("updateAvailable")),
    )
