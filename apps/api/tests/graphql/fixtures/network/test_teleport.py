"""Fixture coverage for typed Teleport VPN settings reads.

# tool: unifi_get_teleport_settings
"""

import pytest
from unifi_core.network.models.teleport import teleport_from_controller

from tests.graphql.fixtures._helpers import bootstrap, graphql_query, stub_managers


@pytest.mark.asyncio
async def test_teleport_settings_range_and_enabled_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "vpn_manager", "get_teleport_settings"): teleport_from_controller(
                {
                    "_id": "teleport-1",
                    "key": "teleport",
                    "site_id": "site-1",
                    "enabled": True,
                    "subnet_cidr": "192.168.2.1/24",
                    "future_field": {"nested": True},
                }
            )
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{ network {{ teleportSettings(controller: "{cid}") {{
            id siteId enabled subnetCidr
        }} }} }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["teleportSettings"] == {
        "id": "teleport-1",
        "siteId": "site-1",
        "enabled": True,
        "subnetCidr": "192.168.2.1/24",
    }
