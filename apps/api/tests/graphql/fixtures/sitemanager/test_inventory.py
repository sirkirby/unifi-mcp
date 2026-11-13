"""Real GraphQL requests over the shared account adapter.

# tool: sitemanager_list_hosts
# tool: sitemanager_get_host
# tool: sitemanager_list_sites
# tool: sitemanager_list_devices
"""

import pytest

from tests.graphql.fixtures.sitemanager._helpers import query_case
from tests.sitemanager_data import CASES, TOKEN


@pytest.mark.asyncio
async def test_account_hosts(tmp_path, monkeypatch):
    data = await query_case(tmp_path, monkeypatch, CASES[0])
    assert data == {
        "items": [
            {
                "id": "synthetic-host",
                "owner": False,
                "registrationTime": 0,
                "applications": [{"name": "network", "isInstalled": False}],
            }
        ],
        "nextCursor": TOKEN,
    }


@pytest.mark.asyncio
async def test_account_host(tmp_path, monkeypatch):
    data = await query_case(tmp_path, monkeypatch, CASES[1])
    assert data == {"id": "synthetic-host", "name": "Synthetic host", "owner": False}


@pytest.mark.asyncio
async def test_account_sites(tmp_path, monkeypatch):
    data = await query_case(tmp_path, monkeypatch, CASES[2])
    assert data == {
        "items": [
            {
                "hostId": "synthetic-host",
                "siteId": "synthetic-site",
                "counts": {"devices": 0},
                "isOwner": False,
                "wanUptimePercent": 0,
            }
        ],
        "nextCursor": TOKEN,
    }


@pytest.mark.asyncio
async def test_account_devices(tmp_path, monkeypatch):
    data = await query_case(tmp_path, monkeypatch, CASES[3])
    assert len(data["items"]) == 1
    assert data["nextCursor"] == TOKEN
    assert data["items"][0] == {
        "hostId": "synthetic-host",
        "updatedAt": 0,
        "devices": [
            {"id": "synthetic-device", "name": "Synthetic device", "isConsole": False, "startupTime": 0},
            {"id": "synthetic-device-two", "name": "Second synthetic device", "isConsole": None, "startupTime": None},
        ],
    }
