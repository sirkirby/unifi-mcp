"""Every InnerSpace query field, resolved through the real core managers.

# tool: innerspace_get_status
# tool: innerspace_get_project
# tool: innerspace_list_floor_plans
# tool: innerspace_list_walls
# tool: innerspace_list_placed_devices
# tool: innerspace_list_access_points
# tool: innerspace_list_switches
# tool: innerspace_list_inventory
# tool: innerspace_get_plan_asset
"""

from __future__ import annotations

import pytest
from unifi_core.innerspace.managers.connection_manager import INTEGRATION_PREFIX

from tests.innerspace_data import DEVICE_IP, MAC, PLAN, SITE, bootstrap, console_cm, graphql, install


@pytest.fixture(autouse=True)
def _db_key(monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")


@pytest.mark.asyncio
async def test_every_innerspace_field(tmp_path):
    app, key, cid = await bootstrap(tmp_path)
    cm = console_cm()
    install(app, cid, cm)
    c = f'controller: "{cid}"'

    body = await graphql(
        app,
        key,
        f"""{{ innerspace {{
            status({c}) {{ installed running version }}
            project({c}, includeShapes: true, unit: "imperial") {{
                unit project {{ title }} plans {{ id imageOffset }} wallTypes {{ name attenuationDb }} shapes
            }}
            floorPlans({c}, innerspaceSiteId: "{SITE}") {{ id name imageFilename scalePerUnit }}
            walls({c}, planId: "{PLAN}", limit: 1) {{ limit total truncated walls {{ id length }} }}
            placedDevices({c}, planId: "{PLAN}") {{ limit total devices {{ id mac height }} }}
            accessPoints({c}, innerspaceSiteId: "{SITE}") {{ id mac }}
            switches({c}) {{ id }}
            inventory({c}) {{ id serial }}
            planAsset({c}, planId: "{PLAN}") {{ filename contentType widthPx }}
        }} }}""",
    )

    assert body.get("errors") is None, body
    data = body["data"]["innerspace"]
    assert data["status"] == {"installed": True, "running": True, "version": "1.4.3"}
    assert data["project"]["unit"] == "imperial"
    assert data["project"]["plans"] == [{"id": PLAN, "imageOffset": [0.0, 0.0]}]
    assert data["project"]["wallTypes"] == [{"name": "Drywall", "attenuationDb": 3.0}]
    assert [shape["id"] for shape in data["project"]["shapes"]] == ["map-1", "wall-1", "wall-2", "device-1"]
    assert data["floorPlans"] == [
        {
            "id": PLAN,
            "name": "Plan A",
            "imageFilename": "00000000-0000-4000-8000-0000000000c2.png",
            "scalePerUnit": 100.0,
        }
    ]
    assert data["walls"]["limit"] == 1 and data["walls"]["total"] == 2 and data["walls"]["truncated"] is True
    assert [wall["id"] for wall in data["walls"]["walls"]] == ["wall-1"]
    assert data["placedDevices"] == {
        "limit": 500,
        "total": 1,
        "devices": [{"id": "device-1", "mac": MAC, "height": 2.5}],
    }
    assert data["accessPoints"] == [{"id": "ap-1", "mac": MAC}]
    assert data["switches"] == [{"id": "sw-1"}]
    assert data["inventory"] == [{"id": "inv-1", "serial": "SYN1"}]
    assert data["planAsset"] == {
        "filename": "00000000-0000-4000-8000-0000000000c2.png",
        "contentType": "image/png",
        "widthPx": 1000.0,
    }
    assert DEVICE_IP not in str(body)
    cm.request_bytes.assert_not_awaited()
    site_reads = [
        call.kwargs.get("params")
        for call in cm.request.await_args_list
        if call.args[1] == f"{INTEGRATION_PREFIX}/access_points"
    ]
    assert site_reads == [{"siteId": SITE}]
