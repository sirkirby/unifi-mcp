"""Fixture e2e tests for access/devices resolvers.

# tool: access_list_devices
# tool: access_get_device
# tool: access_get_device_configs
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import bootstrap, graphql_query, stub_managers


@pytest.mark.asyncio
async def test_access_devices_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "device_manager", "list_devices"): [
                {"id": "dev1", "name": "Reader A", "type": "UA-Reader"},
                {"id": "dev2", "name": "Hub B", "type": "UA-Hub"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ devices(controller: "{cid}", limit: 10) {{
            items {{ id name }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["access"]["devices"]["items"]
    assert len(items) == 2
    assert {it["id"] for it in items} == {"dev1", "dev2"}


@pytest.mark.asyncio
async def test_access_device_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "device_manager", "list_devices"): [
                {"id": "dev1", "name": "Reader A", "type": "UA-Reader"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ device(controller: "{cid}", id: "dev1") {{
            id name
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["access"]["device"]["id"] == "dev1"
    assert body["data"]["access"]["device"]["name"] == "Reader A"


@pytest.mark.asyncio
async def test_access_device_surfaces_structured_location(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "device_manager", "list_devices"): [
                {
                    "id": "dev1",
                    "name": "Hub B",
                    "type": "UA-Hub",
                    "location": {
                        "unique_id": "loc-1",
                        "name": "Front Door",
                        "up_id": "loc-parent",
                        "location_type": "door",
                        "full_name": "Site - Floor 1 - Front Door",
                        "level": 3,
                    },
                },
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ devices(controller: "{cid}", limit: 10) {{
            items {{ id location {{ uniqueId name upId locationType fullName level }} }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    loc = body["data"]["access"]["devices"]["items"][0]["location"]
    assert loc["uniqueId"] == "loc-1"
    assert loc["name"] == "Front Door"
    assert loc["upId"] == "loc-parent"
    assert loc["locationType"] == "door"
    assert loc["fullName"] == "Site - Floor 1 - Front Door"
    assert loc["level"] == 3


@pytest.mark.asyncio
async def test_access_device_configs_list_and_redaction(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "device_manager", "get_device_configs"): {
                "device_id": "dev1",
                "device_name": "Entry Reader",
                "is_camera": True,
                "configs": [
                    {"device_id": "dev1", "key": "show_entry_greet", "value": "yes", "tag": "device_setting"},
                    {"device_id": "dev1", "key": "ssh_password", "value": "s3cr3t", "tag": "credential"},
                ],
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ deviceConfigs(controller: "{cid}", deviceId: "dev1") {{
            items {{ key value tag }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["access"]["deviceConfigs"]["items"]
    by_key = {it["key"]: it for it in items}
    assert by_key["show_entry_greet"]["value"] == "yes"
    # Credential-tagged config secrets must be redacted on the GraphQL surface too.
    assert by_key["ssh_password"]["value"] == "***REDACTED***"


@pytest.mark.asyncio
async def test_access_device_configs_policy_disable_returns_raw(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access", redact_sensitive_fields=False)
    stub_managers(
        monkeypatch,
        {
            ("access", "device_manager", "get_device_configs"): {
                "device_id": "dev1",
                "device_name": "Entry Reader",
                "is_camera": True,
                "configs": [
                    {"device_id": "dev1", "key": "ssh_password", "value": "s3cr3t", "tag": "credential"},
                ],
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ deviceConfigs(controller: "{cid}", deviceId: "dev1") {{
            items {{ key value }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["access"]["deviceConfigs"]["items"]
    # Operator disabled redaction policy → raw secret surfaces (honors the override).
    assert items[0]["value"] == "s3cr3t"
