"""Account SD-WAN fields use the same recursively redacted projections.

# tool: sitemanager_list_sdwan_configs
# tool: sitemanager_get_sdwan_config
# tool: sitemanager_get_sdwan_config_status
"""

import pytest

from tests.graphql.fixtures.sitemanager._helpers import query_case
from tests.sitemanager_data import CASES


@pytest.mark.asyncio
async def test_account_configs(tmp_path, monkeypatch):
    data = await query_case(tmp_path, monkeypatch, CASES[6])
    assert data == {
        "items": [{"id": "synthetic-config", "name": "Synthetic SD-WAN", "type": "hub-and-spoke"}],
        "nextCursor": None,
    }


@pytest.mark.asyncio
async def test_account_config(tmp_path, monkeypatch):
    data = await query_case(tmp_path, monkeypatch, CASES[7])
    assert data == {
        "id": "synthetic-config",
        "settings": {"api_key": "***REDACTED***"},
        "hubs": [{"password": "***REDACTED***"}],
        "spokes": [],
        "variant": "test",
    }


@pytest.mark.asyncio
async def test_account_status(tmp_path, monkeypatch):
    data = await query_case(tmp_path, monkeypatch, CASES[8])
    assert data == {
        "id": "synthetic-config",
        "updatedAt": 0,
        "errors": [{"api_key": "***REDACTED***"}],
        "warnings": [],
        "spokes": [{"secret": "***REDACTED***"}],
    }
