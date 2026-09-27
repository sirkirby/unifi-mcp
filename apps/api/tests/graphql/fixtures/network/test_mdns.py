"""Fixture coverage for typed site-wide mDNS reads.

# tool: unifi_get_mdns_settings
"""

import pytest
from unifi_core.network.models.mdns import mdns_from_controller

from tests.graphql.fixtures._helpers import bootstrap, graphql_query, stub_managers


@pytest.mark.asyncio
async def test_mdns_services_scope_and_nullable_legacy_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "system_manager", "get_mdns_settings"): mdns_from_controller(
                {
                    "_id": "mdns-1",
                    "mode": "custom",
                    "enabled_for": "some",
                    "enabled_for_network_ids": ["network-1"],
                    "predefined_services": [{"code": "printers", "future_field": True}],
                    "custom_services": [{"name": "legacy"}],
                }
            )
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{ network {{ mdnsSettings(controller: "{cid}") {{
            id mode enabledFor enabledForNetworkIds
            predefinedServices {{ code }} customServices {{ name address }}
        }} }} }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["mdnsSettings"] == {
        "id": "mdns-1",
        "mode": "custom",
        "enabledFor": "some",
        "enabledForNetworkIds": ["network-1"],
        "predefinedServices": [{"code": "printers"}],
        "customServices": [{"name": "legacy", "address": None}],
    }
