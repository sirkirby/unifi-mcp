"""Tests for controller-safe chime mutations."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from unifi_core.protect.managers.chime_manager import ChimeManager


@pytest.mark.asyncio
async def test_trigger_chime_validates_before_device_lookup() -> None:
    manager = ChimeManager(MagicMock())
    manager._get_chime = MagicMock()

    with pytest.raises(ValidationError):
        await manager.trigger_chime("chime-1", volume=101, repeat_times=1)

    manager._get_chime.assert_not_called()


@pytest.mark.asyncio
async def test_trigger_chime_plays_with_validated_values() -> None:
    chime = MagicMock(name="Entry Chime", volume=50, repeat_times=1)
    chime.name = "Entry Chime"
    chime.play = AsyncMock()
    manager = ChimeManager(MagicMock())
    manager._get_chime = MagicMock(return_value=chime)

    result = await manager.trigger_chime("chime-1", volume=80, repeat_times=3)

    chime.play.assert_awaited_once_with(volume=80, repeat_times=3)
    assert result == {
        "chime_id": "chime-1",
        "chime_name": "Entry Chime",
        "triggered": True,
        "volume": 80,
        "repeat_times": 3,
    }
