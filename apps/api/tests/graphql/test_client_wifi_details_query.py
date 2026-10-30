"""clientWifiDetails returns every WiFi field, with counters past the 32-bit GraphQL Int."""

from unittest.mock import AsyncMock, patch

import pytest
from unifi_api.graphql.context import GraphQLContext
from unifi_api.graphql.schema import schema

ATTEMPTS = 5_000_000_000
QUERY = """
{
  network {
    clientWifiDetails(controller: "c1", mac: "aa:bb:cc:00:00:01") {
      ap noise satisfaction txRetries wifiTxAttempts roamCount radio bssid nss is11r
    }
  }
}
"""


@pytest.mark.asyncio
async def test_client_wifi_details_query_returns_the_full_shape() -> None:
    raw = {
        "mac": "aa:bb:cc:00:00:01",
        "ap_mac": "aa:bb:cc:00:00:09",
        "noise": -95,
        "satisfaction": 98,
        "tx_retries": 3_000_000_000,
        "wifi_tx_attempts": ATTEMPTS,
        "roam_count": 2,
        "radio": "na",
        "bssid": "aa:bb:cc:00:00:0a",
        "nss": 2,
        "is_11r": True,
    }
    with patch("unifi_api.graphql.resolvers.network._fetch_client_wifi_details", AsyncMock(return_value=raw)):
        result = await schema.execute(QUERY, context_value=GraphQLContext(api_key_scopes="read"))

    assert result.errors is None
    assert result.data["network"]["clientWifiDetails"] == {
        "ap": "aa:bb:cc:00:00:09",
        "noise": -95,
        "satisfaction": 98,
        "txRetries": 3_000_000_000,
        "wifiTxAttempts": ATTEMPTS,
        "roamCount": 2,
        "radio": "na",
        "bssid": "aa:bb:cc:00:00:0a",
        "nss": 2,
        "is11r": True,
    }
