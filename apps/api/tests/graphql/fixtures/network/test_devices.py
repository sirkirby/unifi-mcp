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
    stub_managers(monkeypatch, {
        ("network", "device_manager", "get_devices"): [
            {"mac": "ap:01", "name": "AP-Living", "model": "U7PRO"},
            {"mac": "sw:01", "name": "SW-Core", "model": "USW48"},
        ],
    })
    body = await graphql_query(app, key, f'''{{
        network {{ devices(controller: "{cid}", limit: 10) {{
            items {{ mac name model }}
        }} }}
    }}''')
    assert body.get("errors") is None, body
    items = body["data"]["network"]["devices"]["items"]
    assert len(items) == 2
    names = {it["name"] for it in items}
    assert names == {"AP-Living", "SW-Core"}


@pytest.mark.asyncio
async def test_device_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(monkeypatch, {
        ("network", "device_manager", "get_devices"): [
            {"mac": "ap:01", "name": "AP-Living", "model": "U7PRO"},
        ],
    })
    body = await graphql_query(app, key, f'''{{
        network {{ device(controller: "{cid}", mac: "ap:01") {{
            mac name
        }} }}
    }}''')
    assert body.get("errors") is None, body
    assert body["data"]["network"]["device"]["mac"] == "ap:01"


@pytest.mark.asyncio
async def test_device_radio(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(monkeypatch, {
        ("network", "device_manager", "get_device_radio"): {
            "mac": "ap:01", "radio_table": [],
        },
    })
    body = await graphql_query(app, key, f'''{{
        network {{ deviceRadio(controller: "{cid}", mac: "ap:01") {{
            mac
        }} }}
    }}''')
    assert body.get("errors") is None, body
    assert body["data"]["network"]["deviceRadio"]["mac"] == "ap:01"


@pytest.mark.asyncio
async def test_device_stats(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(monkeypatch, {
        ("network", "stats_manager", "get_device_stats"): [
            {"time": 1000, "tx_bytes": 100},
        ],
    })
    body = await graphql_query(app, key, f'''{{
        network {{ deviceStats(controller: "{cid}", mac: "ap:01") {{
            ts
        }} }}
    }}''')
    assert body.get("errors") is None, body
    assert body["data"]["network"]["deviceStats"][0]["ts"] == 1000 * 1000


@pytest.mark.asyncio
async def test_rogue_aps_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(monkeypatch, {
        ("network", "device_manager", "list_rogue_aps"): [
            {"bssid": "de:ad:be:ef:01:01", "ssid": "EvilNet"},
        ],
    })
    body = await graphql_query(app, key, f'''{{
        network {{ rogueAps(controller: "{cid}", limit: 10) {{
            items {{ bssid ssid }}
        }} }}
    }}''')
    assert body.get("errors") is None, body
    items = body["data"]["network"]["rogueAps"]["items"]
    assert len(items) == 1
    assert items[0]["bssid"] == "de:ad:be:ef:01:01"


@pytest.mark.asyncio
async def test_rf_scan_results(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(monkeypatch, {
        ("network", "device_manager", "get_rf_scan_results"): [
            {"bssid": "aa:bb:cc:dd:ee:01", "channel": 6},
        ],
    })
    body = await graphql_query(app, key, f'''{{
        network {{ rfScanResults(controller: "{cid}", apMac: "ap:01") {{
            bssid channel
        }} }}
    }}''')
    assert body.get("errors") is None, body
    results = body["data"]["network"]["rfScanResults"]
    assert len(results) == 1
    assert results[0]["channel"] == 6


@pytest.mark.asyncio
async def test_available_channels(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(monkeypatch, {
        ("network", "device_manager", "list_available_channels"): [
            {"channel": 1, "band": "2g"},
            {"channel": 36, "band": "5g"},
        ],
    })
    body = await graphql_query(app, key, f'''{{
        network {{ availableChannels(controller: "{cid}") {{
            channel allowed
        }} }}
    }}''')
    assert body.get("errors") is None, body
    channels = body["data"]["network"]["availableChannels"]
    assert len(channels) == 2


@pytest.mark.asyncio
async def test_speedtest_status(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(monkeypatch, {
        ("network", "device_manager", "get_speedtest_status"): {
            "status": "idle", "rundate": 1000,
        },
    })
    body = await graphql_query(app, key, f'''{{
        network {{ speedtestStatus(controller: "{cid}", gatewayMac: "gw:01") {{
            status
        }} }}
    }}''')
    assert body.get("errors") is None, body
    assert body["data"]["network"]["speedtestStatus"]["status"] == "idle"


@pytest.mark.asyncio
async def test_lldp_neighbors(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(monkeypatch, {
        ("network", "switch_manager", "get_lldp_neighbors"): {
            "device_mac": "sw:01", "lldp_table": [],
        },
    })
    body = await graphql_query(app, key, f'''{{
        network {{ lldpNeighbors(controller: "{cid}", deviceMac: "sw:01") {{
            name model
        }} }}
    }}''')
    assert body.get("errors") is None, body
    # Returns the LldpNeighbors wrapper (name/model from device dict)
    assert body["data"]["network"]["lldpNeighbors"] is not None


@pytest.mark.asyncio
async def test_pdu_outlets(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(monkeypatch, {
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
    })
    body = await graphql_query(app, key, f'''{{
        network {{ pduOutlets(controller: "{cid}", mac: "ac:8b:a9:11:22:33") {{
            mac name model outlets {{ index name relayState }}
        }} }}
    }}''')
    assert body.get("errors") is None, body
    pdu = body["data"]["network"]["pduOutlets"]
    assert pdu["mac"] == "ac:8b:a9:11:22:33"
    assert pdu["outlets"][0]["index"] == 1
    assert pdu["outlets"][0]["relayState"] is True
