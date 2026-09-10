"""Public inventory models and explicit, lossy projections into shared read views.

No public UUID is a legacy _id. Unknown legacy fields remain absent/None; callers
must retain source_api and integration_id when presenting these partial records.
"""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PublicSite(BaseModel):
    id: UUID
    internalReference: str
    name: str


class PublicInventory(list[dict[str, Any]]):
    """List-compatible source marker, including an empty public inventory."""

    source_api = "integration"


class PublicInventoryItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: UUID
    name: str | None = None
    macAddress: str | None = None
    ipAddress: str | None = None
    model: str | None = None
    state: str | None = None
    type: str | None = None
    firmwareVersion: str | None = None
    firmwareUpdatable: bool | None = None
    enabled: bool | None = None
    vlanId: int | None = None
    features: list[str] | dict[str, Any] = Field(default_factory=list)
    securityConfiguration: dict[str, Any] = Field(default_factory=dict)

    def inventory_record(self, domain: Literal["devices", "clients", "networks", "wlans"]) -> dict[str, Any]:
        record: dict[str, Any] = {
            "source_api": "integration",
            "integration_id": str(self.id),
            "_id": None,
            "name": self.name,
        }
        if domain in {"devices", "clients"}:
            record.update(mac=self.macAddress, ip=self.ipAddress)
        if domain == "devices":
            # Features can overlap (a gateway can also switch and broadcast).
            # Do not infer a legacy model/type from a display name.
            category = next(
                (
                    name
                    for feature, name in (("gateway", "gateway"), ("accessPoint", "ap"), ("switching", "switch"))
                    if feature in self.features
                ),
                "unknown",
            )
            record.update(
                model=self.model,
                version=self.firmwareVersion,
                upgradable=self.firmwareUpdatable,
                state={"ONLINE": 1, "OFFLINE": 0}.get(self.state),
                public_state=self.state,
                device_category=category,
                adopted=True,
            )
        elif domain == "clients":
            record.update(
                is_wired=True if self.type == "WIRED" else False if self.type == "WIRELESS" else None,
                status="online",
                is_online=True,
            )
        elif domain == "networks":
            record.update(enabled=self.enabled, vlan=self.vlanId)
        elif domain == "wlans":
            record.update(enabled=self.enabled)
        return record
