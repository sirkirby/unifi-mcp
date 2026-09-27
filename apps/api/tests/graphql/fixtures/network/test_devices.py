"""Fixture e2e tests for network/devices resolvers.

# tool: unifi_list_devices
# tool: unifi_get_device_details
# tool: unifi_get_device_radio
# tool: unifi_get_device_stats
# tool: unifi_list_rogue_aps
# tool: unifi_get_rf_scan_results
# tool: unifi_list_available_channels
# tool: unifi_get_speedtest_status
# tool: unifi_get_lldp_neighbors
# tool: unifi_get_pdu_outlets
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import (
    bootstrap,
    graphql_query,
    stub_managers,
)


@pytest.mark.asyncio
async def test_devices_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "device_manager", "get_devices"): [
                {"mac": "ap:01", "name": "AP-Living", "model": "U7PRO"},
                {"mac": "sw:01", "name": "SW-Core", "model": "USW48"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ devices(controller: "{cid}", limit: 10) {{
            items {{ mac name model }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["devices"]["items"]
    assert len(items) == 2
    names = {it["name"] for it in items}
    assert names == {"AP-Living", "SW-Core"}


@pytest.mark.asyncio
async def test_device_detail_matches_equivalent_mac_format(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "device_manager", "get_devices"): [
                {"mac": "aa:bb:cc:dd:ee:01", "name": "AP-Living", "model": "U7PRO"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ device(controller: "{cid}", mac: "AABBCCDDEE01") {{
            mac name
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["device"]["mac"] == "aa:bb:cc:dd:ee:01"


@pytest.mark.asyncio
async def test_device_radio(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "device_manager", "get_device_radio"): {
                "mac": "udm:01",
                "name": "Gateway",
                "radios": [
                    # AP-style raw row: int channel, string ht.
                    {"name": "wifi0", "radio": "ng", "channel": 11, "ht": "20", "current_channel": 11},
                    # Gateway-style raw row: "auto" channel, int ht.
                    {"name": "wifi2", "radio": "6e", "channel": "auto", "ht": 160, "current_channel": 37},
                ],
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ deviceRadio(controller: "{cid}", mac: "udm:01") {{
            mac
            radios {{ radio channel ht currentChannel }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    radio_data = body["data"]["network"]["deviceRadio"]
    assert radio_data["mac"] == "udm:01"
    assert radio_data["radios"] == [
        {"radio": "ng", "channel": 11, "ht": "20", "currentChannel": 11},
        {"radio": "6e", "channel": 0, "ht": "160", "currentChannel": 37},
    ]


@pytest.mark.asyncio
async def test_device_stats(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "stats_manager", "get_device_stats"): [
                {"time": 1000, "tx_bytes": 100},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ deviceStats(controller: "{cid}", mac: "ap:01") {{
            ts
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["deviceStats"][0]["ts"] == 1000 * 1000


@pytest.mark.asyncio
async def test_rogue_aps_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "device_manager", "list_rogue_aps"): [
                {"bssid": "de:ad:be:ef:01:01", "ssid": "EvilNet"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ rogueAps(controller: "{cid}", limit: 10) {{
            items {{ bssid ssid }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["rogueAps"]["items"]
    assert len(items) == 1
    assert items[0]["bssid"] == "de:ad:be:ef:01:01"


@pytest.mark.asyncio
async def test_rf_scan_results(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "device_manager", "get_rf_scan_results"): [
                {"bssid": "aa:bb:cc:dd:ee:01", "channel": 6},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ rfScanResults(controller: "{cid}", apMac: "ap:01") {{
            bssid channel
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    results = body["data"]["network"]["rfScanResults"]
    assert len(results) == 1
    assert results[0]["channel"] == 6


@pytest.mark.asyncio
async def test_available_channels(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "device_manager", "list_available_channels"): [
                {"channel": 1, "band": "2g"},
                {"channel": 36, "band": "5g"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ availableChannels(controller: "{cid}") {{
            channel allowed
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    channels = body["data"]["network"]["availableChannels"]
    assert len(channels) == 2


@pytest.mark.asyncio
async def test_speedtest_status(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "device_manager", "get_speedtest_status"): {
                "status": "idle",
                "rundate": 1000,
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ speedtestStatus(controller: "{cid}", gatewayMac: "gw:01") {{
            status
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["speedtestStatus"]["status"] == "idle"


@pytest.mark.asyncio
async def test_lldp_neighbors(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "switch_manager", "get_lldp_neighbors"): {
                "device_mac": "sw:01",
                "lldp_table": [],
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ lldpNeighbors(controller: "{cid}", deviceMac: "sw:01") {{
            name model
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    # Returns the LldpNeighbors wrapper (name/model from device dict)
    assert body["data"]["network"]["lldpNeighbors"] is not None


@pytest.mark.asyncio
async def test_pdu_outlets(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "device_manager", "get_pdu_outlets"): {
                "mac": "ac:8b:a9:11:22:33",
                "name": "Rack PDU",
                "model": "USPRPS",
                "outlets": [
                    {
                        "index": 1,
                        "name": "Outlet 1",
                        "has_relay": True,
                        "has_metering": True,
                        "relay_state": True,
                        "cycle_enabled": False,
                        "override_relay_state": True,
                        "override_cycle_enabled": False,
                        "has_override": True,
                    },
                ],
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ pduOutlets(controller: "{cid}", mac: "ac:8b:a9:11:22:33") {{
            mac name model outlets {{ index name relayState }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    pdu = body["data"]["network"]["pduOutlets"]
    assert pdu["mac"] == "ac:8b:a9:11:22:33"
    assert pdu["outlets"][0]["index"] == 1
    assert pdu["outlets"][0]["relayState"] is True


@pytest.mark.parametrize(
    "value,expected",
    [
        (42, 42.0),
        ("42.5", 42.5),
        (None, None),
        (True, None),
        ("bad", None),
        ("nan", None),
        (float("inf"), None),
        ({}, None),
    ],
)
def test_device_health_temperature_parsing(value, expected):
    from unifi_api.graphql.types.network.device import Device

    assert Device.from_manager_output({"general_temperature": value}).general_temperature == expected


def test_device_health_shapes_and_primary_stats_key():
    from unifi_api.graphql.types.network.device import Device

    device = Device.from_manager_output(
        {"system-stats": {"cpu": "12"}, "system_stats": {"cpu": "99"}, "temperatures": {}, "uptime_stats": []}
    )
    assert device.system_stats == {"cpu": "12"}
    assert device.temperatures is None
    assert device.uptime_stats is None
    assert Device.from_manager_output({"system_stats": {"mem": "21"}}).system_stats == {"mem": "21"}
    empty = Device.from_manager_output({}).to_dict()
    assert all(empty[k] is None for k in ("system_stats", "general_temperature", "temperatures", "uptime_stats"))


@pytest.mark.asyncio
@pytest.mark.parametrize("redact", [True, False])
async def test_device_health_rest_graphql_parity_and_policy(tmp_path, monkeypatch, redact):
    from httpx import ASGITransport, AsyncClient

    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network", redact_sensitive_fields=redact)
    raw = {
        "mac": "aa:bb:cc:dd:ee:01",
        "system-stats": {"cpu": "12", "api_key": "secret"},
        "general_temperature": "42.5",
        "temperatures": [{"name": "board", "value": 43, "password": "secret"}],
        "uptime_stats": {"WAN": {"monitors": [{"latency_average": 4, "token": "secret"}]}},
    }
    stub_managers(
        monkeypatch,
        {("network", "device_manager", "get_devices"): [raw], ("network", "device_manager", "get_device_details"): raw},
    )
    fields = "system_stats general_temperature temperatures uptime_stats"
    selection = (
        "system_stats: systemStats general_temperature: generalTemperature temperatures uptime_stats: uptimeStats"
    )
    body = await graphql_query(
        app,
        key,
        f'''{{ network {{
            devices(controller:"{cid}") {{ items {{ {selection} }} }}
            device(controller:"{cid}",mac:"aa:bb:cc:dd:ee:01") {{ {selection} }}
        }} }}''',
    )
    assert not body.get("errors"), body
    item = body["data"]["network"]["devices"]["items"][0]
    assert item == body["data"]["network"]["device"]
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test", headers={"Authorization": f"Bearer {key}"}
    ) as client:
        response = await client.get(f"/v1/sites/default/devices?controller={cid}")
        assert response.status_code == 200
        rest = response.json()["items"][0]
        detail = await client.get(f"/v1/sites/default/devices/aa:bb:cc:dd:ee:01?controller={cid}")
        assert detail.status_code == 200
        assert {k: rest[k] for k in fields.split()} == item
        assert {k: detail.json()["data"][k] for k in fields.split()} == item
    expected = "***REDACTED***" if redact else "secret"
    assert item["system_stats"]["api_key"] == expected
    assert item["temperatures"][0]["password"] == expected
    assert item["uptime_stats"]["WAN"]["monitors"][0]["token"] == expected
    assert raw["system-stats"]["api_key"] == "secret"
