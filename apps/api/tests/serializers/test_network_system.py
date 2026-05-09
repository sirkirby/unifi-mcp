"""Network system cluster type unit tests.

Phase 6 PR2 Task 23 migrated all nine read projections to Strawberry types
in ``unifi_api.graphql.types.network.system``. The mutation ack still
lives in the legacy serializer module — see
``test_system_mutation_acks_dispatch`` below.
"""

from unifi_api.graphql.types.network.system import (
    Alarm,
    AutoBackupSettings,
    Backup,
    EventTypes,
    NetworkHealth,
    SiteSettings,
    SnmpSettings,
    SpeedtestResult,
    SystemInfo,
    TopClient,
)
from unifi_api.serializers._registry import (
    discover_serializers,
    serializer_registry_singleton,
)


def _registry():
    discover_serializers(manifest_tool_names=set())
    return serializer_registry_singleton()


# ---- Alarms ----


def test_alarm_list_serializer_shape() -> None:
    sample = {
        "_id": "al1", "key": "EVT_FW_Block", "msg": "Blocked",
        "archived": False, "time": 1714000000,
    }
    item = Alarm.from_manager_output(sample).to_dict()
    assert Alarm.render_hint("list")["kind"] == "list"
    assert item["id"] == "al1"
    assert item["key"] == "EVT_FW_Block"
    assert item["msg"] == "Blocked"
    assert item["archived"] is False
    assert item["time"] == 1714000000


# ---- Backups ----


def test_backup_list_serializer_shape() -> None:
    sample = {"_id": "b1", "filename": "auto-2026-04-29.unf", "size": 12345, "time": 1714000000}
    item = Backup.from_manager_output(sample).to_dict()
    assert Backup.render_hint("list")["kind"] == "list"
    assert item["id"] == "b1"
    assert item["filename"] == "auto-2026-04-29.unf"
    assert item["size"] == 12345
    assert item["created_at"] == 1714000000


# ---- System info ----


def test_system_info_detail_serializer_shape() -> None:
    sample = {
        "name": "UniFi Controller",
        "version": "8.1.113",
        "hostname": "unifi.local",
        "uptime": 86400,
        "num_devices": 12,
        "num_clients": 47,
    }
    out = SystemInfo.from_manager_output(sample).to_dict()
    assert SystemInfo.render_hint("detail")["kind"] == "detail"
    assert out["name"] == "UniFi Controller"
    assert out["version"] == "8.1.113"
    assert out["uptime"] == 86400
    assert out["num_devices"] == 12


# ---- Network health (manager returns list of subsystems) ----


def test_network_health_list_serializer_shape() -> None:
    sample = [
        {"subsystem": "wan", "status": "ok", "num_user": 5, "num_guest": 1, "num_iot": 2, "rx_bytes-r": 100, "tx_bytes-r": 200},
        {"subsystem": "wlan", "status": "ok", "num_user": 8},
    ]
    rows = [NetworkHealth.from_manager_output(r).to_dict() for r in sample]
    assert NetworkHealth.render_hint("list")["kind"] == "list"
    assert rows[0]["subsystem"] == "wan"
    assert rows[0]["status"] == "ok"
    assert rows[0]["num_user"] == 5
    assert rows[0]["rx_bytes"] == 100
    assert rows[0]["tx_bytes"] == 200
    assert rows[1]["subsystem"] == "wlan"


# ---- Site settings (DETAIL) ----


def test_site_settings_detail_serializer_shape() -> None:
    """SiteSettings projects display fields from the manager's
    ``{raw, sections}`` shape — name from super_identity, country from
    the country section."""
    sample = {
        "raw": [],
        "sections": {
            "super_identity": {
                "_id": "site_id_1",
                "name": "default",
                "role": "admin",
                "key": "super_identity",
            },
            "country": {"code": "840", "key": "country"},
        },
    }
    out = SiteSettings.from_manager_output(sample).to_dict()
    assert SiteSettings.render_hint("detail")["kind"] == "detail"
    assert out["site_id"] == "site_id_1"
    assert out["name"] == "default"
    assert out["role"] == "admin"
    assert out["country"] == 840


def test_site_settings_serializer_handles_missing_sections() -> None:
    """Sections absent from the firmware leave the corresponding fields None."""
    out = SiteSettings.from_manager_output({"raw": [], "sections": {}}).to_dict()
    assert out["name"] is None
    assert out["country"] is None


# ---- SNMP settings (manager returns list[dict]) ----


def test_snmp_settings_detail_first_item_unwrap() -> None:
    sample = [{"enabled": True, "community": "public", "port": 161, "version": "v2c", "key": "snmp"}]
    out = SnmpSettings.from_manager_output(sample).to_dict()
    assert SnmpSettings.render_hint("detail")["kind"] == "detail"
    assert out["enabled"] is True
    assert out["community"] == "public"
    assert out["port"] == 161
    assert out["version"] == "v2c"


# ---- Event types ----


def test_event_types_detail_serializer_shape() -> None:
    sample = [
        {"prefix": "EVT_WU_", "description": "Wireless user events"},
        {"prefix": "EVT_SW_", "description": "Switch events"},
    ]
    out = EventTypes.from_manager_output(sample).to_dict()
    assert EventTypes.render_hint("detail")["kind"] == "detail"
    assert out["event_types"][0]["prefix"] == "EVT_WU_"
    assert out["event_types"][1]["prefix"] == "EVT_SW_"


# ---- Auto-backup settings ----


def test_autobackup_settings_detail_serializer_shape() -> None:
    sample = {"enabled": True, "schedule": "daily", "max_count": 10}
    out = AutoBackupSettings.from_manager_output(sample).to_dict()
    assert AutoBackupSettings.render_hint("detail")["kind"] == "detail"
    assert out["enabled"] is True
    assert out["schedule"] == "daily"
    assert out["max_count"] == 10


# ---- Top clients ----


def test_top_clients_list_serializer_shape() -> None:
    sample = {"mac": "aa:bb:cc:dd:ee:ff", "name": "laptop", "rx_bytes": 100, "tx_bytes": 200, "total_bytes": 300}
    item = TopClient.from_manager_output(sample).to_dict()
    assert TopClient.render_hint("list")["kind"] == "list"
    assert item["mac"] == "aa:bb:cc:dd:ee:ff"
    assert item["hostname"] == "laptop"
    assert item["rx_bytes"] == 100
    assert item["tx_bytes"] == 200
    assert item["total_bytes"] == 300


# ---- Speedtest ----


def test_speedtest_list_serializer_shape() -> None:
    sample = {"time": 1714000000, "xput_download": 500.5, "xput_upload": 50.1, "latency": 12}
    item = SpeedtestResult.from_manager_output(sample).to_dict()
    assert SpeedtestResult.render_hint("list")["kind"] == "list"
    assert item["timestamp"] == 1714000000
    assert item["download_mbps"] == 500.5
    assert item["upload_mbps"] == 50.1
    assert item["latency_ms"] == 12


# ---- System mutation acks (still serializer-backed) ----


def test_system_mutation_acks_dispatch() -> None:
    reg = _registry()
    for tool in (
        "unifi_archive_alarm",
        "unifi_archive_all_alarms",
        "unifi_create_backup",
        "unifi_delete_backup",
        "unifi_update_autobackup_settings",
    ):
        s = reg.serializer_for_tool(tool)
        out = s.serialize_action(True, tool_name=tool)
        assert out["render_hint"]["kind"] == "detail"
        assert out["data"]["success"] is True


def test_create_backup_returns_dict_passthrough() -> None:
    reg = _registry()
    s = reg.serializer_for_tool("unifi_create_backup")
    sample = {"filename": "backup.unf", "url": "/dl/backup/backup.unf"}
    out = s.serialize_action(sample, tool_name="unifi_create_backup")
    assert out["data"]["filename"] == "backup.unf"
