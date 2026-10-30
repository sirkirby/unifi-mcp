"""speedtestResults timestamps are epoch milliseconds, past the 32-bit GraphQL Int."""

from unittest.mock import AsyncMock, patch

import pytest
from unifi_api.graphql.context import GraphQLContext
from unifi_api.graphql.schema import schema

TIME_MS = 1_793_355_467_788
QUERY = """
{
  network {
    speedtestResults(controller: "c1") {
      items { timestamp downloadMbps wanNetworkgroup interfaceName }
    }
  }
}
"""


@pytest.mark.asyncio
async def test_speedtest_timestamp_survives_serialization() -> None:
    row = {"time": TIME_MS, "download_mbps": 1230, "wan_networkgroup": "WAN2", "interface_name": "eth8"}
    with patch("unifi_api.graphql.resolvers.network._fetch_speedtest_results", AsyncMock(return_value=[row])):
        result = await schema.execute(QUERY, context_value=GraphQLContext(api_key_scopes="read"))

    assert result.errors is None
    (item,) = result.data["network"]["speedtestResults"]["items"]
    assert item == {"timestamp": TIME_MS, "downloadMbps": 1230, "wanNetworkgroup": "WAN2", "interfaceName": "eth8"}
