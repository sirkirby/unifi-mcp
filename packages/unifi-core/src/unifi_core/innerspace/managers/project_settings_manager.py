"""InnerSpace project settings: the project unit (``PATCH /api/project {unit}``, reply ``{}``)."""

from __future__ import annotations

from functools import partial
from typing import Any

from unifi_core.innerspace.managers._layout import Snapshot, WritePlan, WriteRequest, apply_write, preview_write, state
from unifi_core.innerspace.managers.connection_manager import (
    INTERNAL_PROJECT_PATH,
    InnerSpaceConnectionManager,
    reconnects_on_demand,
)
from unifi_core.innerspace.models._coerce import as_dict
from unifi_core.innerspace.models.writes import ProjectUnitInput
from unifi_core.innerspace.units import Unit
from unifi_core.write_verification import WriteVerificationResult

_UNIT = "set InnerSpace project unit"


def _unit(args: ProjectUnitInput, snapshot: Snapshot) -> WritePlan:
    current = as_dict(snapshot.data.get("project")).get("unit")

    def request(_: list[str]) -> WriteRequest:
        def expect(after: Snapshot) -> dict[str, bool | None]:
            return {"unit": state(as_dict(after.data.get("project")), {"unit": args.unit}, {"unit": current})}

        return WriteRequest("PATCH", INTERNAL_PROJECT_PATH, {"unit": args.unit}, expect)

    return WritePlan(
        preview={"current": {"unit": current}, "proposed": {"unit": args.unit}},
        request=None if current == args.unit else request,
        warnings=[
            "Only the display unit changes: stored shapes keep their values, and reads without a unit argument "
            "return lengths in the new unit"
        ],
    )


@reconnects_on_demand
class InnerSpaceProjectSettingsManager:
    def __init__(self, cm: InnerSpaceConnectionManager) -> None:
        self._cm = cm

    async def preview_set_project_unit(self, unit: Unit) -> dict[str, Any]:
        """The project's current and proposed unit."""
        args = ProjectUnitInput(unit=unit)
        return await preview_write(self._cm, operation=_UNIT, build=partial(_unit, args))

    async def apply_set_project_unit(self, unit: Unit) -> WriteVerificationResult:
        """Set the project's display unit (``metric`` or ``imperial``)."""
        args = ProjectUnitInput(unit=unit)
        return await apply_write(
            self._cm, operation=_UNIT, tool="innerspace_set_project_unit", args=args, build=partial(_unit, args)
        )
