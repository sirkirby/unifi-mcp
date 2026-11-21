"""InnerSpace application status on the console."""

from __future__ import annotations

import strawberry

from unifi_api.graphql.types.innerspace._base import Projection


@strawberry.type(description="Whether the InnerSpace application is installed and running on the UniFi OS console.")
class InnerSpaceStatus(Projection):
    installed: bool = strawberry.field(description="Whether the InnerSpace application is installed")
    running: bool = strawberry.field(description="Whether the InnerSpace application is running")
    version: str | None = strawberry.field(description="Installed version")
    update_available: str | None = strawberry.field(description="Version available as an update, if any")

    _columns = ["installed", "running", "version"]
