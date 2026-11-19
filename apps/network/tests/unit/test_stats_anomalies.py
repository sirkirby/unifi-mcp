"""The anomalies tool never reports Network 11's empty legacy answer as no anomalies."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiounifi.errors import ResponseError

from unifi_core.network.managers.stats_manager import StatsManager

NO_ENGINE = ResponseError("Call https://h/proxy/network/v2/api/stats/source received 404 Not Found")


def _stats_manager(source, anomalies):
    connection = MagicMock()
    connection.site = "default"
    connection.get_cached.return_value = None

    async def request(api_request):
        if api_request.path == "/source":
            if isinstance(source, BaseException):
                raise source
            return source
        assert api_request.path == "/stat/anomalies"
        return anomalies

    connection.request = AsyncMock(side_effect=request)
    return StatsManager(connection, MagicMock())


@pytest.mark.asyncio
@pytest.mark.parametrize("duration", ["daily", "weekly"])
async def test_network_11_anomalies_are_reported_unavailable(duration):
    with patch("unifi_network_mcp.tools.stats.stats_manager", _stats_manager(["MODERN"], [])):
        from unifi_network_mcp.tools.stats import get_anomalies

        result = await get_anomalies(duration=duration)

    assert result["success"] is False
    assert "unavailable" in result["error"]
    assert "Network 11" in result["error"]
    assert "anomalies" not in result


@pytest.mark.asyncio
async def test_a_legacy_controller_with_no_anomalies_reports_an_empty_success():
    with patch("unifi_network_mcp.tools.stats.stats_manager", _stats_manager(NO_ENGINE, [])):
        from unifi_network_mcp.tools.stats import get_anomalies

        result = await get_anomalies(duration="daily")

    assert result["success"] is True
    assert result["count"] == 0
