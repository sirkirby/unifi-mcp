"""Unknown filter values are refused, never echoed as if applied (#947)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.network.managers.stats_manager import StatsGroupingError, StatsManager
from unifi_core.network.read_views import shape_client_list, shape_device_list

DEVICES = [
    {"mac": "aa:00:00:00:00:01", "name": "ap-1", "type": "uap", "state": 1},
    {"mac": "aa:00:00:00:00:02", "name": "ap-2", "type": "uap", "state": 0},
    {"mac": "aa:00:00:00:00:03", "name": "sw-1", "type": "usw", "state": 1},
]
CLIENTS = [
    {"mac": "bb:00:00:00:00:01", "name": "phone", "is_wired": False},
    {"mac": "bb:00:00:00:00:02", "name": "desk", "is_wired": True},
]


@pytest.mark.parametrize(
    ("kwargs", "named"),
    [({"device_type": "access_point"}, "device_type"), ({"status": "connected"}, "status")],
)
def test_unknown_device_filter_is_refused_with_the_valid_values(kwargs, named):
    result = shape_device_list(DEVICES, site="default", **kwargs)

    assert result["success"] is False
    assert f"Invalid {named}" in result["error"]
    assert "ap" in result["error"] if named == "device_type" else "online" in result["error"]
    assert "devices" not in result


def test_known_device_filters_still_filter():
    assert shape_device_list(DEVICES, site="default", device_type="ap", fields="name")["total_count"] == 2
    assert shape_device_list(DEVICES, site="default", status="online", fields="name")["total_count"] == 2
    assert (
        shape_device_list(DEVICES, site="default", device_type="ap", status="offline", fields="name")["total_count"]
        == 1
    )


def test_unknown_client_filter_type_is_refused():
    result = shape_client_list(CLIENTS, site="default", filter_type="wifi")

    assert result["success"] is False
    assert "Invalid filter_type 'wifi'" in result["error"] and "wireless" in result["error"]


def test_known_client_filter_types_still_filter():
    assert shape_client_list(CLIENTS, site="default", filter_type="wireless")["total_count"] == 1
    assert shape_client_list(CLIENTS, site="default", filter_type="all")["total_count"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get_site_dpi_traffic", "get_client_dpi_traffic"])
async def test_unknown_dpi_grouping_is_refused_before_any_request(method):
    connection = MagicMock()
    connection.site = "default"
    connection.get_cached.return_value = None
    connection.request = AsyncMock()
    manager = StatsManager(connection, MagicMock())
    args = ("bb:00:00:00:00:01",) if method == "get_client_dpi_traffic" else ()

    with pytest.raises(StatsGroupingError, match="Invalid group_by: must be one of by_app, by_cat"):
        await getattr(manager, method)(*args, by="category")

    connection.request.assert_not_awaited()
