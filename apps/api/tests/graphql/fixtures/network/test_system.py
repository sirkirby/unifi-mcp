"""Fixture e2e tests for network/system resolvers.

# tool: unifi_get_system_info
# tool: unifi_get_site_settings
# tool: unifi_get_snmp_settings
# tool: unifi_get_autobackup_settings
# tool: unifi_list_backups
# tool: unifi_get_event_types
# tool: unifi_list_vouchers
# tool: unifi_get_voucher_details
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import (
    bootstrap,
    graphql_query,
    stub_managers,
)


@pytest.mark.asyncio
async def test_system_info(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(monkeypatch, {
        ("network", "system_manager", "get_system_info"): {
            "name": "MyController",
            "version": "7.4.0",
            "hostname": "unifi.local",
            "uptime": 86400,
        },
    })
    body = await graphql_query(app, key, f'''{{
        network {{ systemInfo(controller: "{cid}") {{
            name version hostname uptime
        }} }}
    }}''')
    assert body.get("errors") is None, body
    info = body["data"]["network"]["systemInfo"]
    assert info["name"] == "MyController"
    assert info["version"] == "7.4.0"


@pytest.mark.asyncio
async def test_site_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(monkeypatch, {
        ("network", "system_manager", "get_site_settings"): {
            "raw": [],
            "sections": {
                "super_identity": {"_id": "default", "name": "Home"},
                "country": {"code": "840"},
            },
        },
    })
    body = await graphql_query(app, key, f'''{{
        network {{ siteSettings(controller: "{cid}") {{
            siteId name country
        }} }}
    }}''')
    assert body.get("errors") is None, body
    settings = body["data"]["network"]["siteSettings"]
    assert settings["siteId"] == "default"
    assert settings["name"] == "Home"
    assert settings["country"] == 840


@pytest.mark.asyncio
async def test_snmp_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(monkeypatch, {
        ("network", "system_manager", "get_settings"): [
            {"enabled": True, "community": "public", "port": 161},
        ],
    })
    body = await graphql_query(app, key, f'''{{
        network {{ snmpSettings(controller: "{cid}") {{
            enabled community port
        }} }}
    }}''')
    assert body.get("errors") is None, body
    snmp = body["data"]["network"]["snmpSettings"]
    assert snmp["enabled"] is True
    assert snmp["community"] == "public"


@pytest.mark.asyncio
async def test_autobackup_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(monkeypatch, {
        ("network", "system_manager", "get_autobackup_settings"): {
            "enabled": True,
            "schedule": "0 2 * * *",
            "max_count": 5,
        },
    })
    body = await graphql_query(app, key, f'''{{
        network {{ autobackupSettings(controller: "{cid}") {{
            enabled schedule maxCount
        }} }}
    }}''')
    assert body.get("errors") is None, body
    ab = body["data"]["network"]["autobackupSettings"]
    assert ab["enabled"] is True
    assert ab["maxCount"] == 5


@pytest.mark.asyncio
async def test_backups_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(monkeypatch, {
        ("network", "system_manager", "list_backups"): [
            {"_id": "bk-1", "filename": "backup_2024.unf", "time": 1000000},
            {"_id": "bk-2", "filename": "backup_2025.unf", "time": 2000000},
        ],
    })
    body = await graphql_query(app, key, f'''{{
        network {{ backups(controller: "{cid}", limit: 10) {{
            items {{ id filename }}
        }} }}
    }}''')
    assert body.get("errors") is None, body
    items = body["data"]["network"]["backups"]["items"]
    assert len(items) == 2
    filenames = {it["filename"] for it in items}
    assert filenames == {"backup_2024.unf", "backup_2025.unf"}


@pytest.mark.asyncio
async def test_event_types(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(monkeypatch, {
        ("network", "event_manager", "get_event_type_prefixes"): [
            {"key": "EVT_AP", "label": "Access Point Events"},
            {"key": "EVT_GW", "label": "Gateway Events"},
        ],
    })
    body = await graphql_query(app, key, f'''{{
        network {{ eventTypes(controller: "{cid}") {{
            eventTypes
        }} }}
    }}''')
    assert body.get("errors") is None, body
    et = body["data"]["network"]["eventTypes"]
    assert et is not None
    assert len(et["eventTypes"]) == 2


@pytest.mark.asyncio
async def test_vouchers_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(monkeypatch, {
        ("network", "hotspot_manager", "get_vouchers"): [
            {"_id": "vc-1", "code": "ABC-123", "status": "unused"},
            {"_id": "vc-2", "code": "DEF-456", "status": "used"},
        ],
    })
    body = await graphql_query(app, key, f'''{{
        network {{ vouchers(controller: "{cid}", limit: 10) {{
            items {{ id code status }}
        }} }}
    }}''')
    assert body.get("errors") is None, body
    items = body["data"]["network"]["vouchers"]["items"]
    assert len(items) == 2
    codes = {it["code"] for it in items}
    assert codes == {"ABC-123", "DEF-456"}


@pytest.mark.asyncio
async def test_voucher_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(monkeypatch, {
        ("network", "hotspot_manager", "get_voucher_details"): {
            "_id": "vc-1", "code": "ABC-123", "status": "unused",
        },
    })
    body = await graphql_query(app, key, f'''{{
        network {{ voucher(controller: "{cid}", id: "vc-1") {{
            id code status
        }} }}
    }}''')
    assert body.get("errors") is None, body
    v = body["data"]["network"]["voucher"]
    assert v["code"] == "ABC-123"
