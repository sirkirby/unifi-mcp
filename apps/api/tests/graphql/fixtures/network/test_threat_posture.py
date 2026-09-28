"""Fixture proof for typed posture and large/unknown values.

# tool: unifi_get_threat_posture
"""

import pytest
from unifi_core.network.models.threat_posture import threat_posture_from_controller

from tests.graphql.fixtures._helpers import bootstrap, graphql_query, stub_managers


@pytest.mark.asyncio
async def test_threat_posture_resolver_preserves_large_and_unknown_values(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "system_manager", "get_threat_posture"): threat_posture_from_controller(
                "DAY", {"scanned_bytes": 2**40, "ips_enabled": True, "updated_timestamp": 1786225096952}, []
            )
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{ network {{ threatPosture(controller: "{cid}") {{
        period scannedBytes ipsEnabled hasSubscription threats updatedTimestamp gatewaySignatures {{ ruleCount }}
    }} }} }}''',
    )
    assert not body.get("errors"), body
    data = body["data"]["network"]["threatPosture"]
    assert data == {
        "period": "DAY",
        "scannedBytes": 2**40,
        "ipsEnabled": True,
        "hasSubscription": None,
        "threats": None,
        "updatedTimestamp": 1786225096952,
        "gatewaySignatures": [],
    }
