"""Fixture e2e tests for network/observability resolvers.

# tool: unifi_list_events
# tool: unifi_get_alerts
# tool: unifi_get_anomalies
# tool: unifi_get_ips_events
# tool: unifi_list_alarms
# tool: unifi_get_dashboard
# tool: unifi_get_gateway_stats
# tool: unifi_get_client_stats
# tool: unifi_get_client_dpi_traffic
# tool: unifi_get_site_dpi_traffic
# tool: unifi_get_top_clients
# tool: unifi_get_speedtest_results
# tool: unifi_get_speedtest_status
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import (
    bootstrap,
    graphql_query,
    stub_managers,
)


@pytest.mark.asyncio
async def test_event_log_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "event_manager", "get_events"): [
                {"_id": "ev-1", "key": "EVT_AP_Connected", "msg": "AP connected", "time": 1000},
                {"_id": "ev-2", "key": "EVT_AP_Disconnected", "msg": "AP disconnected", "time": 2000},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ eventLog(controller: "{cid}", limit: 10) {{
            items {{ id key msg }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["eventLog"]["items"]
    assert len(items) == 2


@pytest.mark.asyncio
async def test_alerts(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "stats_manager", "get_alerts"): [
                {"_id": "al-1", "key": "WIFI_INTERFERENCE", "msg": "Interference detected"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ alerts(controller: "{cid}", limit: 10) {{
            items {{ id key msg }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["alerts"]["items"]
    assert len(items) == 1


@pytest.mark.asyncio
async def test_anomalies(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "stats_manager", "get_anomalies"): [
                {"_id": "an-1", "key": "BANDWIDTH_SPIKE", "msg": "Spike detected"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ anomalies(controller: "{cid}", limit: 10) {{
            items {{ id key }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["anomalies"]["items"]
    assert len(items) == 1


@pytest.mark.asyncio
async def test_ips_events(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "stats_manager", "get_ips_events"): [
                {"_id": "ips-1", "key": "IDS_THREAT", "msg": "Threat detected"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ ipsEvents(controller: "{cid}", limit: 10) {{
            items {{ id key }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["ipsEvents"]["items"]
    assert len(items) == 1


@pytest.mark.asyncio
async def test_alarms_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "event_manager", "get_alarms"): [
                {"_id": "arm-1", "key": "ALARM_DEVICE_DOWN", "msg": "Device offline", "archived": False},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ alarms(controller: "{cid}", limit: 10) {{
            items {{ id key archived }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["alarms"]["items"]
    assert len(items) == 1
    assert items[0]["archived"] is False


@pytest.mark.asyncio
async def test_dashboard_stats(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "stats_manager", "get_dashboard"): [
                {"time": 1000, "num_user": 5},
                {"time": 2000, "num_user": 8},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ dashboardStats(controller: "{cid}") {{
            ts
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    stats = body["data"]["network"]["dashboardStats"]
    assert len(stats) == 2


@pytest.mark.asyncio
async def test_gateway_stats(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "stats_manager", "get_gateway_stats"): [
                {"time": 1000, "wan_rx_bytes": 1024},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ gatewayStats(controller: "{cid}") {{
            ts
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    stats = body["data"]["network"]["gatewayStats"]
    assert len(stats) == 1


@pytest.mark.asyncio
async def test_client_stats(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "stats_manager", "get_client_stats"): [
                {"time": 1000, "rx_bytes": 500},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ clientStats(controller: "{cid}", mac: "aa:01") {{
            ts
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    stats = body["data"]["network"]["clientStats"]
    assert len(stats) == 1


@pytest.mark.asyncio
async def test_client_dpi_traffic(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "stats_manager", "get_client_dpi_traffic"): [
                {"time": 1000, "app": 101, "cat": 1},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ clientDpiTraffic(controller: "{cid}", mac: "aa:01") {{
            ts
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    traffic = body["data"]["network"]["clientDpiTraffic"]
    assert len(traffic) == 1


@pytest.mark.asyncio
async def test_site_dpi_traffic(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "stats_manager", "get_site_dpi_traffic"): [
                {"time": 1000, "rx_bytes": 2048},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ siteDpiTraffic(controller: "{cid}") {{
            ts
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    traffic = body["data"]["network"]["siteDpiTraffic"]
    assert len(traffic) == 1


@pytest.mark.asyncio
async def test_top_clients(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "stats_manager", "get_top_clients"): [
                {"mac": "aa:01", "hostname": "heavy-user", "tx_bytes": 10000000},
                {"mac": "aa:02", "hostname": "lite-user", "tx_bytes": 1000},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ topClients(controller: "{cid}") {{
            mac hostname txBytes
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    clients = body["data"]["network"]["topClients"]
    assert len(clients) == 2


@pytest.mark.asyncio
async def test_speedtest_results(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "stats_manager", "get_speedtest_results"): [
                {"time": 1000000000, "xput_download": 500.0, "xput_upload": 100.0},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ speedtestResults(controller: "{cid}") {{
            items {{ timestamp downloadMbps }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["speedtestResults"]["items"]
    assert len(items) == 1
    assert items[0]["downloadMbps"] == 500.0
