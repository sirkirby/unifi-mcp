"""Fixture e2e tests for cross-resource relationship edges.

These edges aren't enumerated in type_registry._tool_types (the resolver-
coverage gate only counts list/detail tools), so they need their own
fixture coverage to prevent silent regressions in the cross-resource
fan-in pattern.

Each test:
1. Stubs ManagerFactory.get_domain_manager for both parent and child managers
2. Queries the parent resource AND its edge field via GraphQL
3. Asserts the child data resolves correctly through the edge

Edge inventory (11 edges, all present in schema.graphql):
  network:
    Client.device          — client → its connected AP
    Device.portClients     — device → clients on a specific port/AP
    Network.clients        — network → all clients on it
  protect:
    Camera.events          — camera → its event stream
    Camera.recordings      — camera → its recording windows
    Liveview.cameraDetails — liveview → camera details
    Recording.cameraDetail — recording → its parent camera
  access:
    Door.policyAssignments — door → assigned access policies
    User.credentials       — user → their credentials
    AccessEvent.door       — event → the door it occurred at
    AccessEvent.user       — event → the user involved
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import bootstrap, graphql_query, stub_managers

# ---------------------------------------------------------------------------
# network: Client.device
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edge_client_device(tmp_path, monkeypatch):
    """Client.device — client resolves to its connected AP via ap_mac lookup."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "client_manager", "get_clients"): [
                {"mac": "aa:bb:cc:dd:ee:01", "ap_mac": "ap:01:02:03:04:05"},
            ],
            ("network", "device_manager", "get_devices"): [
                {"mac": "ap:01:02:03:04:05", "name": "Living Room AP", "model": "U7PRO"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ clients(controller: "{cid}") {{
            items {{ mac device {{ name model }} }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    item = body["data"]["network"]["clients"]["items"][0]
    assert item["device"] is not None
    assert item["device"]["name"] == "Living Room AP"
    assert item["device"]["model"] == "U7PRO"


# ---------------------------------------------------------------------------
# network: Device.portClients
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edge_device_port_clients(tmp_path, monkeypatch):
    """Device.portClients — device resolves to clients whose ap_mac matches."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "device_manager", "get_devices"): [
                {"mac": "ap:01:02:03:04:05", "name": "Hallway AP", "model": "U6LITE"},
            ],
            ("network", "client_manager", "get_clients"): [
                {"mac": "cc:dd:ee:ff:00:01", "hostname": "laptop", "ap_mac": "ap:01:02:03:04:05"},
                {"mac": "cc:dd:ee:ff:00:02", "hostname": "phone", "ap_mac": "ap:01:02:03:04:05"},
                # client on a different AP — should NOT appear
                {"mac": "cc:dd:ee:ff:00:03", "hostname": "tv", "ap_mac": "ap:99:99:99:99:99"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ device(controller: "{cid}", mac: "ap:01:02:03:04:05") {{
            name portClients {{ mac hostname }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    dev = body["data"]["network"]["device"]
    assert dev["name"] == "Hallway AP"
    port_macs = {c["mac"] for c in dev["portClients"]}
    assert port_macs == {"cc:dd:ee:ff:00:01", "cc:dd:ee:ff:00:02"}
    assert "cc:dd:ee:ff:00:03" not in port_macs


# ---------------------------------------------------------------------------
# network: Network.clients
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edge_network_clients(tmp_path, monkeypatch):
    """Network.clients — network resolves to clients whose network_id matches."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "network_manager", "get_networks"): [
                {"_id": "net-trusted", "name": "Trusted", "enabled": True},
            ],
            ("network", "client_manager", "get_clients"): [
                {"mac": "aa:11:22:33:44:01", "hostname": "desktop", "network_id": "net-trusted"},
                {"mac": "aa:11:22:33:44:02", "hostname": "tablet", "network_id": "net-trusted"},
                # client on another network — should NOT appear
                {"mac": "aa:11:22:33:44:03", "hostname": "guest", "network_id": "net-guest"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ networkDetail(controller: "{cid}", id: "net-trusted") {{
            name clients {{ mac hostname }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    net = body["data"]["network"]["networkDetail"]
    assert net["name"] == "Trusted"
    client_macs = {c["mac"] for c in net["clients"]}
    assert client_macs == {"aa:11:22:33:44:01", "aa:11:22:33:44:02"}
    assert "aa:11:22:33:44:03" not in client_macs


# ---------------------------------------------------------------------------
# protect: Camera.events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edge_camera_events(tmp_path, monkeypatch):
    """Camera.events — camera resolves to events whose camera_id matches."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "camera_manager", "list_cameras"): [
                {"id": "cam-1", "name": "Front Door", "model": "G4PRO"},
            ],
            ("protect", "event_manager", "list_events"): [
                {"id": "evt-1", "type": "motion", "camera_id": "cam-1"},
                {"id": "evt-2", "type": "ring", "camera_id": "cam-1"},
                # event for a different camera — should NOT appear
                {"id": "evt-3", "type": "motion", "camera_id": "cam-2"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ camera(controller: "{cid}", id: "cam-1") {{
            name events {{ id type }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    cam = body["data"]["protect"]["camera"]
    assert cam["name"] == "Front Door"
    event_ids = {e["id"] for e in cam["events"]}
    assert event_ids == {"evt-1", "evt-2"}
    assert "evt-3" not in event_ids


# ---------------------------------------------------------------------------
# protect: Camera.recordings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edge_camera_recordings(tmp_path, monkeypatch):
    """Camera.recordings — camera resolves to its recording windows."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "camera_manager", "list_cameras"): [
                {"id": "cam-1", "name": "Garage", "model": "G5FLEX"},
            ],
            ("protect", "recording_manager", "list_recordings"): [
                {
                    "id": "rec-1",
                    "type": "continuous",
                    "camera_id": "cam-1",
                    # start/end must be integer epoch-ms for the pagination key fn
                    "start": 1704067200,
                    "end": 1704070800,
                    "file_size": 102400,
                },
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ camera(controller: "{cid}", id: "cam-1") {{
            name recordings {{ id type start }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    cam = body["data"]["protect"]["camera"]
    assert cam["name"] == "Garage"
    assert len(cam["recordings"]) == 1
    assert cam["recordings"][0]["id"] == "rec-1"
    assert cam["recordings"][0]["type"] == "continuous"


# ---------------------------------------------------------------------------
# protect: Liveview.cameraDetails
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edge_liveview_camera_details(tmp_path, monkeypatch):
    """Liveview.cameraDetails — liveview resolves to typed Camera rows for its slots.

    There is no liveview(id:) detail resolver — only a paginated list.
    We query the list and pick the first item to exercise the edge.
    """
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "camera_manager", "list_cameras"): [
                {"id": "cam-1", "name": "Front Door", "model": "G4PRO"},
                {"id": "cam-2", "name": "Back Yard", "model": "G4BULLET"},
                # cam-3 NOT in the liveview slots
                {"id": "cam-3", "name": "Side Gate", "model": "G3INSTANT"},
            ],
            ("protect", "liveview_manager", "list_liveviews"): [
                {
                    "id": "lv-1",
                    "name": "Main View",
                    "layout": 2,
                    "slots": [
                        {"camera_ids": ["cam-1", "cam-2"]},
                    ],
                    "slot_count": 1,
                    "camera_count": 2,
                    "is_default": True,
                    "is_global": False,
                    "owner_id": "u1",
                },
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ liveviews(controller: "{cid}", limit: 10) {{
            items {{ id name cameraDetails {{ id name }} }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["protect"]["liveviews"]["items"]
    assert len(items) == 1
    lv = items[0]
    assert lv["name"] == "Main View"
    detail_ids = {c["id"] for c in lv["cameraDetails"]}
    assert detail_ids == {"cam-1", "cam-2"}
    assert "cam-3" not in detail_ids


# ---------------------------------------------------------------------------
# protect: Recording.cameraDetail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edge_recording_camera_detail(tmp_path, monkeypatch):
    """Recording.cameraDetail — recording resolves to its parent camera."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")
    stub_managers(
        monkeypatch,
        {
            ("protect", "recording_manager", "list_recordings"): [
                {
                    "id": "rec-1",
                    "type": "continuous",
                    "camera_id": "cam-1",
                    # start/end must be integer epoch-ms for the pagination key fn
                    "start": 1704067200,
                    "end": 1704070800,
                    "file_size": 51200,
                },
            ],
            ("protect", "camera_manager", "list_cameras"): [
                {"id": "cam-1", "name": "Driveway", "model": "G4DOORBELL"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        protect {{ recordings(controller: "{cid}", cameraId: "cam-1") {{
            items {{ id type cameraDetail {{ id name model }} }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["protect"]["recordings"]["items"]
    assert len(items) == 1
    detail = items[0]["cameraDetail"]
    assert detail is not None
    assert detail["id"] == "cam-1"
    assert detail["name"] == "Driveway"
    assert detail["model"] == "G4DOORBELL"


# ---------------------------------------------------------------------------
# access: Door.policyAssignments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edge_door_policy_assignments(tmp_path, monkeypatch):
    """Door.policyAssignments — door resolves to policies that include its id."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "door_manager", "list_doors"): [
                {"id": "door-1", "name": "Main Entrance", "is_locked": False},
            ],
            ("access", "policy_manager", "list_policies"): [
                {"id": "pol-1", "name": "Staff Access", "door_ids": ["door-1"]},
                {"id": "pol-2", "name": "Admin Access", "door_ids": ["door-1", "door-2"]},
                # policy for a different door only — should NOT appear
                {"id": "pol-3", "name": "Server Room", "door_ids": ["door-2"]},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ door(controller: "{cid}", id: "door-1") {{
            name policyAssignments {{ id name }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    door = body["data"]["access"]["door"]
    assert door["name"] == "Main Entrance"
    policy_ids = {p["id"] for p in door["policyAssignments"]}
    assert policy_ids == {"pol-1", "pol-2"}
    assert "pol-3" not in policy_ids


# ---------------------------------------------------------------------------
# access: User.credentials
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edge_user_credentials(tmp_path, monkeypatch):
    """User.credentials — user resolves to credentials whose user_id matches.

    There is no user(id:) detail resolver — only a paginated list.
    We query the list and pick the matching item to exercise the edge.
    """
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "system_manager", "list_users"): [
                {"id": "user-1", "name": "Alice Smith", "status": "active"},
            ],
            ("access", "credential_manager", "list_credentials"): [
                {"id": "cred-1", "user_id": "user-1", "type": "nfc", "status": "active"},
                {"id": "cred-2", "user_id": "user-1", "type": "pin", "status": "active"},
                # credential for another user — should NOT appear
                {"id": "cred-3", "user_id": "user-2", "type": "nfc", "status": "active"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ users(controller: "{cid}", limit: 10) {{
            items {{ id name credentials {{ id type status }} }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["access"]["users"]["items"]
    assert len(items) == 1
    user = items[0]
    assert user["name"] == "Alice Smith"
    cred_ids = {c["id"] for c in user["credentials"]}
    assert cred_ids == {"cred-1", "cred-2"}
    assert "cred-3" not in cred_ids


# ---------------------------------------------------------------------------
# access: AccessEvent.door
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edge_access_event_door(tmp_path, monkeypatch):
    """AccessEvent.door — event resolves to the door it occurred at."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "event_manager", "list_events"): [
                {
                    "id": "evt-1",
                    "type": "access",
                    "door_id": "door-1",
                    "user_id": "user-1",
                    "result": "granted",
                },
            ],
            ("access", "door_manager", "list_doors"): [
                {"id": "door-1", "name": "Front Gate", "is_locked": False},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ events(controller: "{cid}", limit: 10) {{
            items {{ id result door {{ id name }} }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["access"]["events"]["items"]
    assert len(items) == 1
    door = items[0]["door"]
    assert door is not None
    assert door["id"] == "door-1"
    assert door["name"] == "Front Gate"


# ---------------------------------------------------------------------------
# access: AccessEvent.user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edge_access_event_user(tmp_path, monkeypatch):
    """AccessEvent.user — event resolves to the user involved."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "event_manager", "list_events"): [
                {
                    "id": "evt-2",
                    "type": "access",
                    "door_id": "door-1",
                    "user_id": "user-42",
                    "result": "denied",
                },
            ],
            ("access", "system_manager", "list_users"): [
                {"id": "user-42", "name": "Bob Jones", "status": "active", "role": "employee"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ events(controller: "{cid}", limit: 10) {{
            items {{ id result user {{ id name role }} }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["access"]["events"]["items"]
    assert len(items) == 1
    user = items[0]["user"]
    assert user is not None
    assert user["id"] == "user-42"
    assert user["name"] == "Bob Jones"
    assert user["role"] == "employee"
