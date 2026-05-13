"""Pydantic input models for Access action tools.

Action tools (lock/unlock door, reboot device, revoke credential,
delete visitor) take typed action parameters rather than a round-trip
domain object. Each input class lives here.

The class-level ``__action_input__`` flag marks these as out-of-scope
for the cross-layer field-symmetry test — they have no Strawberry read
shape to compare against. Tools import the relevant input class and
validate kwargs via ``ToolInput(**kwargs)`` at the top of the body.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field


class LockDoorInput(BaseModel):
    """Input for ``access_lock_door``."""

    __action_input__: ClassVar[bool] = True

    door_id: str = Field(description="Door UUID")


class UnlockDoorInput(BaseModel):
    """Input for ``access_unlock_door``."""

    __action_input__: ClassVar[bool] = True

    door_id: str = Field(description="Door UUID")
    duration: int = Field(default=2, ge=1, le=300, description="Unlock duration in seconds (1-300)")


class RebootDeviceInput(BaseModel):
    """Input for ``access_reboot_device``."""

    __action_input__: ClassVar[bool] = True

    device_id: str = Field(description="Device UUID")


class RevokeCredentialInput(BaseModel):
    """Input for ``access_revoke_credential``."""

    __action_input__: ClassVar[bool] = True

    credential_id: str = Field(description="Credential UUID")


class DeleteVisitorInput(BaseModel):
    """Input for ``access_delete_visitor``."""

    __action_input__: ClassVar[bool] = True

    visitor_id: str = Field(description="Visitor UUID")
