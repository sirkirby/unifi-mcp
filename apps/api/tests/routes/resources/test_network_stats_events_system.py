"""Phase 5A PR2 Cluster 6 — network stats / events / system routes."""

from datetime import datetime, timezone
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from unifi_api.auth.api_key import generate_key, hash_key
from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig
from unifi_api.db.crypto import ColumnCipher, derive_key
from unifi_api.db.models import ApiKey, Base, Controller
from unifi_api.server import create_app


def _cfg(tmp_path):
    return ApiConfig(
        http=HttpConfig(host="127.0.0.1", port=8080, cors_origins=()),
        logging=LoggingConfig(level="WARNING"),
        db=DbConfig(path=str(tmp_path / "state.db")),
    )


async def _bootstrap(tmp_path, products="network"):
    app = create_app(_cfg(tmp_path))
    async with app.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = app.state.sessionmaker
    cipher = ColumnCipher(derive_key("k"))
    cid = str(uuid.uuid4())
    material = generate_key()
    async with sm() as session:
        session.add(ApiKey(
            id=str(uuid.uuid4()), prefix=material.prefix,
            hash=hash_key(material.plaintext), scopes="read",
            name="t", created_at=datetime.now(timezone.utc),
        ))
        session.add(Controller(
            id=cid, name="N", base_url="https://x", product_kinds=products,
            credentials_blob=cipher.encrypt(b'{"username":"u","password":"p","api_token":null}'),
            verify_tls=False, is_default=True,
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        ))
        await session.commit()
    return app, material.plaintext, cid


class _FakeCM:
    def __init__(self) -> None:
        self.site = "default"

    async def initialize(self) -> None:
        return None

    async def set_site(self, s: str) -> None:
        self.site = s


def _stub_connection(app, cid: str) -> _FakeCM:
    fake = _FakeCM()
    app.state.manager_factory._connection_cache[(cid, "network")] = fake
    return fake


# ---------- TIMESERIES stats ----------


@pytest.mark.asyncio
async def test_get_dashboard_stats_timeseries(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    points = [
        {"time": 1700000000000, "rx_bytes": 100, "tx_bytes": 200,
         "wan-rx_bytes": 10, "wan-tx_bytes": 20},
        {"time": 1700000060000, "rx_bytes": 110, "tx_bytes": 220,
         "wan-rx_bytes": 11, "wan-tx_bytes": 22},
    ]

    async def fake_get(self):
        return points

    from unifi_core.network.managers.stats_manager import StatsManager
    monkeypatch.setattr(StatsManager, "get_dashboard", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/stats/dashboard?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "timeseries"
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_get_network_stats_timeseries(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self, duration_hours=1, granularity="hourly"):
        return [{"time": 1700000000000, "rx_bytes": 1, "tx_bytes": 2}]

    from unifi_core.network.managers.stats_manager import StatsManager
    monkeypatch.setattr(StatsManager, "get_network_stats", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/stats/network?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "timeseries"
    assert len(body["items"]) == 1


@pytest.mark.asyncio
async def test_get_gateway_stats_timeseries(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self, duration_hours=24, granularity="hourly"):
        return [{"time": 1700000000000, "wan-rx_bytes": 5, "wan-tx_bytes": 7}]

    from unifi_core.network.managers.stats_manager import StatsManager
    monkeypatch.setattr(StatsManager, "get_gateway_stats", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/stats/gateway?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["render_hint"]["kind"] == "timeseries"


@pytest.mark.asyncio
async def test_get_site_dpi_traffic_timeseries(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self, by="by_app"):
        return [{"app": 1, "rx_bytes": 5, "tx_bytes": 7}]

    from unifi_core.network.managers.stats_manager import StatsManager
    monkeypatch.setattr(StatsManager, "get_site_dpi_traffic", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/stats/dpi/site?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["render_hint"]["kind"] == "timeseries"


@pytest.mark.asyncio
async def test_get_client_dpi_traffic_with_mac(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self, client_mac, by="by_app"):
        assert client_mac == "aa:bb:cc:dd:ee:ff"
        return [{"app": 1, "rx_bytes": 5, "tx_bytes": 7}]

    from unifi_core.network.managers.stats_manager import StatsManager
    monkeypatch.setattr(StatsManager, "get_client_dpi_traffic", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/stats/dpi/clients/aa:bb:cc:dd:ee:ff?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["render_hint"]["kind"] == "timeseries"


# ---------- TIMESERIES stats (PR4 dispatch override now points at
# stats_manager.get_X_stats which returns list[point]) ----------


@pytest.mark.asyncio
async def test_get_device_stats_with_mac_timeseries(tmp_path, monkeypatch) -> None:
    """device-stats now TIMESERIES; dispatch override routes to stats_manager.get_device_stats."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_stats(self, mac, *args, **kwargs):
        assert mac == "11:22:33:44:55:66"
        return [
            {"time": 1_700_000_000, "rx_bytes": 1, "tx_bytes": 2},
            {"time": 1_700_000_300, "rx_bytes": 3, "tx_bytes": 4},
        ]

    from unifi_core.network.managers.stats_manager import StatsManager
    monkeypatch.setattr(StatsManager, "get_device_stats", fake_stats)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/stats/devices/11:22:33:44:55:66?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "timeseries"
    assert isinstance(body["items"], list) and len(body["items"]) == 2


@pytest.mark.asyncio
async def test_get_client_stats_with_mac_timeseries(tmp_path, monkeypatch) -> None:
    """client-stats now TIMESERIES; dispatch override routes to stats_manager.get_client_stats."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_stats(self, mac, *args, **kwargs):
        assert mac == "aa:bb:cc:dd:ee:ff"
        return [{"timestamp": 1_700_000_000_000, "tx_bytes": 100}]

    from unifi_core.network.managers.stats_manager import StatsManager
    monkeypatch.setattr(StatsManager, "get_client_stats", fake_stats)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/stats/clients/aa:bb:cc:dd:ee:ff?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "timeseries"
    assert isinstance(body["items"], list)


@pytest.mark.asyncio
async def test_get_dpi_stats_detail(tmp_path, monkeypatch) -> None:
    """dpi-stats currently DETAIL; manager method get_dpi_stats."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self, by_app=False, client_mac=None):
        return {"by_app": [], "by_cat": []}

    from unifi_core.network.managers.stats_manager import StatsManager
    monkeypatch.setattr(StatsManager, "get_dpi_stats", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/stats/dpi?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "detail"


# ---------- EVENT_LOG ----------


@pytest.mark.asyncio
async def test_list_events_event_log(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self, within=24, limit=100, start=0, event_type=None,
                       categories=None, severities=None):
        return [
            {"_id": "e1", "time": 1700000000000, "key": "EVT_WU_Connected", "msg": "alice connected"},
            {"_id": "e2", "time": 1700000060000, "key": "EVT_WU_Disconnected", "msg": "bob left"},
        ]

    from unifi_core.network.managers.event_manager import EventManager
    monkeypatch.setattr(EventManager, "get_events", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/events?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "event_log"
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_get_alerts_event_log(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self, include_archived=False):
        return [{"_id": "a1", "time": 1700000000000, "key": "EVT_AD_AdminLogin", "msg": "admin login"}]

    from unifi_core.network.managers.stats_manager import StatsManager
    monkeypatch.setattr(StatsManager, "get_alerts", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/alerts?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "event_log"
    assert len(body["items"]) == 1


@pytest.mark.asyncio
async def test_get_anomalies_event_log(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self, duration_hours=24):
        return [{"_id": "x1", "time": 1700000000000, "key": "ANOMALY", "msg": "weird"}]

    from unifi_core.network.managers.stats_manager import StatsManager
    monkeypatch.setattr(StatsManager, "get_anomalies", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/anomalies?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["render_hint"]["kind"] == "event_log"


@pytest.mark.asyncio
async def test_get_ips_events_event_log(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self, duration_hours=24, limit=50):
        return [{"_id": "i1", "time": 1700000000000, "key": "IPS", "msg": "blocked"}]

    from unifi_core.network.managers.stats_manager import StatsManager
    monkeypatch.setattr(StatsManager, "get_ips_events", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/ips-events?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["render_hint"]["kind"] == "event_log"


# ---------- LIST ----------


@pytest.mark.asyncio
async def test_list_alarms_list(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self, archived=False, limit=100):
        return [{"_id": "alarm1", "time": 1700000000000, "key": "EVT_NU_LostContact",
                 "msg": "device offline", "archived": False}]

    from unifi_core.network.managers.event_manager import EventManager
    monkeypatch.setattr(EventManager, "get_alarms", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/alarms?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "list"
    assert len(body["items"]) == 1


@pytest.mark.asyncio
async def test_list_backups_list(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self):
        return [{"_id": "b1", "filename": "backup.unf", "time": 1700000000000, "size": 1234}]

    from unifi_core.network.managers.system_manager import SystemManager
    monkeypatch.setattr(SystemManager, "list_backups", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/backups?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["render_hint"]["kind"] == "list"


@pytest.mark.asyncio
async def test_get_top_clients_list(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self, duration_hours=24, limit=10):
        return [{"mac": "aa:bb:cc:dd:ee:ff", "hostname": "alice", "total_bytes": 1000}]

    from unifi_core.network.managers.stats_manager import StatsManager
    monkeypatch.setattr(StatsManager, "get_top_clients", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/top-clients?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["render_hint"]["kind"] == "list"


@pytest.mark.asyncio
async def test_get_client_sessions_list(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self, client_mac=None, within_hours=168, limit=100):
        return [{"_id": "s1", "mac": "aa:bb:cc:dd:ee:ff", "assoc_time": 1700000000,
                 "duration": 100}]

    from unifi_core.network.managers.stats_manager import StatsManager
    monkeypatch.setattr(StatsManager, "get_client_sessions", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/client-sessions?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["render_hint"]["kind"] == "list"


@pytest.mark.asyncio
async def test_get_network_health_list(tmp_path, monkeypatch) -> None:
    """network-health is registered LIST per Phase 4A — multi-element list of subsystems."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self):
        return [
            {"subsystem": "wlan", "status": "ok", "num_user": 5},
            {"subsystem": "lan", "status": "ok", "num_user": 0},
        ]

    from unifi_core.network.managers.system_manager import SystemManager
    monkeypatch.setattr(SystemManager, "get_network_health", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/network-health?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "list"
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_get_speedtest_results_list(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self, duration_hours=24):
        return [{"_id": "st1", "timestamp": 1700000000, "download_mbps": 100,
                 "upload_mbps": 50, "latency_ms": 10}]

    from unifi_core.network.managers.stats_manager import StatsManager
    monkeypatch.setattr(StatsManager, "get_speedtest_results", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/speedtest-results?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["render_hint"]["kind"] == "list"


# ---------- DETAIL ----------


@pytest.mark.asyncio
async def test_get_event_types_detail(tmp_path, monkeypatch) -> None:
    """event-types: event_manager.get_event_type_prefixes (synchronous, returns list)."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    def fake_get(self):
        return [{"prefix": "EVT_WU_", "description": "Wireless user"}]

    from unifi_core.network.managers.event_manager import EventManager
    monkeypatch.setattr(EventManager, "get_event_type_prefixes", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/event-types?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["render_hint"]["kind"] == "detail"


@pytest.mark.asyncio
async def test_get_autobackup_settings_detail(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self):
        return {"backup_max_files": 5, "backup_schedule": "daily"}

    from unifi_core.network.managers.system_manager import SystemManager
    monkeypatch.setattr(SystemManager, "get_autobackup_settings", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/autobackup-settings?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["render_hint"]["kind"] == "detail"


@pytest.mark.asyncio
async def test_get_site_settings_detail(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self):
        return {
            "raw": [],
            "sections": {
                "super_identity": {"name": "default", "_id": "default"},
                "country": {"code": "840"},
            },
        }

    from unifi_core.network.managers.system_manager import SystemManager
    monkeypatch.setattr(SystemManager, "get_site_settings", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/site-settings?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["render_hint"]["kind"] == "detail"


@pytest.mark.asyncio
async def test_get_system_info_detail(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self):
        return {"version": "8.0.0", "uptime": 12345}

    from unifi_core.network.managers.system_manager import SystemManager
    monkeypatch.setattr(SystemManager, "get_system_info", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/system-info?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["render_hint"]["kind"] == "detail"


@pytest.mark.asyncio
async def test_get_client_wifi_details_with_mac_detail(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self, client_mac):
        assert client_mac == "aa:bb:cc:dd:ee:ff"
        return {"mac": client_mac, "essid": "MyWifi", "rssi": -55}

    from unifi_core.network.managers.stats_manager import StatsManager
    monkeypatch.setattr(StatsManager, "get_client_wifi_details", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/client-wifi-details/aa:bb:cc:dd:ee:ff?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "detail"


# ---------- capability mismatch ----------


@pytest.mark.asyncio
async def test_stats_dashboard_capability_mismatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path, products="protect")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/stats/dashboard?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 409
    assert r.json()["detail"]["kind"] == "capability_mismatch"
