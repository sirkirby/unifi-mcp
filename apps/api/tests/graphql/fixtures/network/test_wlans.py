"""Fixture e2e tests for network/wlans resolvers.

# tool: unifi_list_wlans
# tool: unifi_get_wlan_details
"""

from __future__ import annotations

import pytest
from unifi_core.redaction import REDACTED

from tests.graphql.fixtures._helpers import (
    bootstrap,
    graphql_query,
    stub_managers,
)


@pytest.mark.asyncio
async def test_wlans_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "network_manager", "get_wlans"): [
                {"_id": "wl-1", "name": "HomeNet", "security": "wpapsk"},
                {"_id": "wl-2", "name": "GuestNet", "security": "open"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ wlans(controller: "{cid}", limit: 10) {{
            items {{ id name }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["wlans"]["items"]
    assert len(items) == 2
    names = {it["name"] for it in items}
    assert names == {"HomeNet", "GuestNet"}


@pytest.mark.asyncio
async def test_wlan_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "network_manager", "get_wlans"): [
                {"_id": "wl-1", "name": "HomeNet", "x_passphrase": "wifi-secret"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ wlan(controller: "{cid}", id: "wl-1") {{
            id name xPassphrase
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["wlan"]["id"] == "wl-1"
    assert body["data"]["network"]["wlan"]["xPassphrase"] == REDACTED


@pytest.mark.asyncio
async def test_wlan_detail_policy_disabled_returns_raw_passphrase(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network", redact_sensitive_fields=False)
    stub_managers(
        monkeypatch,
        {
            ("network", "network_manager", "get_wlans"): [
                {"_id": "wl-1", "name": "HomeNet", "x_passphrase": "wifi-secret"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ wlan(controller: "{cid}", id: "wl-1") {{
            id name xPassphrase
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["wlan"]["xPassphrase"] == "wifi-secret"


@pytest.mark.asyncio
async def test_wlan_detail_reads_multicast_enhance_controller_key(tmp_path, monkeypatch):
    """The controller reports multicast enhancement as ``mcastenhance_enabled``.

    Reading the public field name instead left this null for every WLAN, so the
    GraphQL surface reported the setting as unset even where the controller had
    a definite value for it.
    """
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "network_manager", "get_wlans"): [
                {"_id": "wl-1", "name": "HomeNet", "mcastenhance_enabled": True},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ wlan(controller: "{cid}", id: "wl-1") {{
            id multicastEnhanceEnabled
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["wlan"]["multicastEnhanceEnabled"] is True


@pytest.mark.asyncio
async def test_wlan_detail_exposes_schedule_windows(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    windows = [
        {
            "duration_minutes": 360,
            "name": "Weeknight outage",
            "start_days_of_week": ["mon", "tue", "wed", "thu", "fri"],
            "start_hour": 1,
            "start_minute": 0,
        }
    ]
    stub_managers(
        monkeypatch,
        {
            ("network", "network_manager", "get_wlans"): [
                {
                    "_id": "wl-1",
                    "name": "HomeNet",
                    "schedule_enabled": True,
                    "schedule_reversed": True,
                    "schedule": ["mon-fri|0100-0700"],
                    "schedule_with_duration": windows,
                },
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ wlan(controller: "{cid}", id: "wl-1") {{
            scheduleEnabled scheduleReversed schedule
            scheduleWithDuration {{
                durationMinutes name startDaysOfWeek startHour startMinute
            }}
        }} }}
    }}''',
    )

    assert body.get("errors") is None, body
    wlan = body["data"]["network"]["wlan"]
    assert wlan["scheduleEnabled"] is True
    assert wlan["scheduleReversed"] is True
    assert wlan["schedule"] == ["mon-fri|0100-0700"]
    assert wlan["scheduleWithDuration"] == [
        {
            "durationMinutes": 360,
            "name": "Weeknight outage",
            "startDaysOfWeek": ["mon", "tue", "wed", "thu", "fri"],
            "startHour": 1,
            "startMinute": 0,
        }
    ]
