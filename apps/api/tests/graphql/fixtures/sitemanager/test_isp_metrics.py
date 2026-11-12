"""Account metrics fields preserve the full-window summary and partial result.

# tool: sitemanager_get_isp_metrics
# tool: sitemanager_query_isp_metrics
"""

import pytest

from tests.graphql.fixtures.sitemanager._helpers import query_case
from tests.sitemanager_data import CASES


@pytest.mark.asyncio
async def test_account_isp_metrics(tmp_path, monkeypatch):
    data = await query_case(tmp_path, monkeypatch, CASES[4])
    assert data == {
        "items": [
            {
                "hostId": "synthetic-host",
                "siteId": "synthetic-site",
                "summary": {"periodCount": 3, "avgLatencyMs": 10},
                "periods": [
                    {"time": 0, "avgLatencyMs": 0},
                    {"time": "2026-01-01T01:00:00Z", "avgLatencyMs": 10},
                    {"time": 2, "avgLatencyMs": 20},
                ],
            }
        ],
        "count": 1,
        "nextCursor": None,
    }


@pytest.mark.asyncio
async def test_account_query_metrics(tmp_path, monkeypatch):
    data = await query_case(tmp_path, monkeypatch, CASES[5])
    assert data == {
        "items": [{"siteId": "synthetic-site"}],
        "count": 1,
        "partial": True,
        "message": "One synthetic site omitted",
        "nextCursor": None,
    }
