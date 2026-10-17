"""Protect memory is reported in KiB; health exposes bytes across all surfaces."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from uiprotect.data.nvr import MemoryInfo
from unifi_core.protect.managers.system_manager import SystemManager


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Reported UNVR (4 GiB) and upstream uiprotect UNVR-PRO (8 GiB) data.
        (
            {"available": 790_356, "free": 69_984, "total": 4_040_180},
            {"available_bytes": 809_324_544, "free_bytes": 71_663_616, "total_bytes": 4_137_144_320},
        ),
        (
            {"available": 6_388_164, "free": 102_208, "total": 8_163_024},
            {"available_bytes": 6_541_479_936, "free_bytes": 104_660_992, "total_bytes": 8_358_936_576},
        ),
        ({}, {"available_bytes": None, "free_bytes": None, "total_bytes": None}),
        (
            {"available": None, "free": 0, "total": 1},
            {"available_bytes": None, "free_bytes": 0, "total_bytes": 1024},
        ),
    ],
)
async def test_health_converts_sdk_memory_kib_to_bytes(raw, expected):
    storage = SimpleNamespace(available=123, size=456, used=333, is_recycling=False, type="hdd")
    nvr = SimpleNamespace(
        system_info=SimpleNamespace(
            cpu=SimpleNamespace(average_load=0.5, temperature=42),
            memory=MemoryInfo(**raw),
            storage=storage,
        ),
        is_updating=False,
        uptime=timedelta(seconds=60),
    )
    cm = SimpleNamespace(client=SimpleNamespace(bootstrap=SimpleNamespace(nvr=nvr)))

    health = await SystemManager(cm).get_health()

    assert health["memory"] == expected
    assert health["storage"] == {
        "available_bytes": 123,
        "size_bytes": 456,
        "used_bytes": 333,
        "is_recycling": False,
        "type": "hdd",
    }
