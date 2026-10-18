"""topClients byte counters must survive GraphQL serialization above 2 GiB."""

from unittest.mock import AsyncMock, patch

import pytest
from unifi_api.graphql.context import GraphQLContext
from unifi_api.graphql.schema import schema

GB_43 = 43 * 1024**3
QUERY = """
{
  network {
    topClients(controller: "c1", withinHours: 24) {
      mac uploadBytes downloadBytes rxBytes txBytes totalBytes source
    }
  }
}
"""


@pytest.mark.asyncio
async def test_top_clients_byte_fields_exceed_32_bit_int() -> None:
    row = {
        "mac": "aa:bb:cc:00:00:01",
        "upload_bytes": GB_43,
        "download_bytes": GB_43 + 1,
        "rx_bytes": GB_43,
        "tx_bytes": GB_43 + 1,
        "total_bytes": 2 * GB_43 + 1,
        "source": "report",
    }
    with patch("unifi_api.graphql.resolvers.network._fetch_top_clients", AsyncMock(return_value=[row])):
        result = await schema.execute(QUERY, context_value=GraphQLContext(api_key_scopes="read"))

    assert result.errors is None
    (client,) = result.data["network"]["topClients"]
    assert client == {
        "mac": "aa:bb:cc:00:00:01",
        "uploadBytes": GB_43,
        "downloadBytes": GB_43 + 1,
        "rxBytes": GB_43,
        "txBytes": GB_43 + 1,
        "totalBytes": 2 * GB_43 + 1,
        "source": "report",
    }
