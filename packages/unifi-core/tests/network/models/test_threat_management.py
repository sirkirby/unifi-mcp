"""Tests for threat management (IDS/IPS) and DPI model and settings read."""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiounifi.errors import AiounifiException
from unifi_core.network.managers.system_manager import SystemManager
from unifi_core.network.models.threat_management import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    ThreatManagementSettings,
    threat_management_from_controller,
)
from unifi_core.redaction import redact_sensitive_fields

SECRET_TOKEN = "synthetic-utm-token-secret-999"


def test_field_sets_and_read_only_contract():
    assert MUTABLE_FIELDS == frozenset(
        {"ips_mode", "enabled_categories", "traffic_identification_enabled", "device_fingerprinting_enabled"}
    )
    assert READ_ONLY_FIELDS == frozenset({"enabled", "enabled_networks", "advanced_filtering_preference"})
    assert MUTABLE_FIELDS | READ_ONLY_FIELDS == set(ThreatManagementSettings.model_fields)
    for name, field in ThreatManagementSettings.model_fields.items():
        assert ((field.json_schema_extra or {}).get("mutable") is False) == (name in READ_ONLY_FIELDS)


@pytest.mark.parametrize(
    "mode,expected_enabled",
    [
        ("ids", True),
        ("ips", True),
        ("ipsInline", True),
        ("disabled", False),
    ],
)
def test_known_ips_modes_normalized(mode: str, expected_enabled: bool):
    settings = threat_management_from_controller(ips={"ips_mode": mode})
    assert settings.ips_mode == mode
    assert settings.enabled is expected_enabled


@pytest.mark.parametrize(
    "unknown_mode",
    [
        "monitor_only",
        "custom",
        "ids_passive",
        "BLOCK",
    ],
)
def test_unknown_ips_mode_preserved_with_none_enabled(unknown_mode: str):
    settings = threat_management_from_controller(ips={"ips_mode": unknown_mode})
    assert settings.ips_mode == unknown_mode
    assert settings.enabled is None


def test_missing_and_malformed_ips_mode():
    assert threat_management_from_controller(ips={}).ips_mode is None
    assert threat_management_from_controller(ips={}).enabled is None
    assert threat_management_from_controller(ips={"ips_mode": 123}).ips_mode is None
    assert threat_management_from_controller(ips={"ips_mode": None}).ips_mode is None
    assert threat_management_from_controller(None, None).ips_mode is None


def test_categories_and_networks_handling():
    # Absent -> None
    s1 = threat_management_from_controller(ips={})
    assert s1.enabled_categories is None
    assert s1.enabled_networks is None

    # Present empty list -> empty list
    s2 = threat_management_from_controller(ips={"enabled_categories": [], "enabled_networks": []})
    assert s2.enabled_categories == []
    assert s2.enabled_networks == []

    # Valid string lists preserved
    s3 = threat_management_from_controller(
        ips={
            "enabled_categories": ["p2p", "tor", "malware"],
            "enabled_networks": ["net-1", "net-2"],
        }
    )
    assert s3.enabled_categories == ["p2p", "tor", "malware"]
    assert s3.enabled_networks == ["net-1", "net-2"]

    # Malformed list contents return None (never filter to misleading subsets)
    s4 = threat_management_from_controller(
        ips={
            "enabled_categories": ["tor", 123, None, "botnet"],
            "enabled_networks": ["n1", {}, []],
        }
    )
    assert s4.enabled_categories is None
    assert s4.enabled_networks is None

    s5 = threat_management_from_controller(
        ips={
            "enabled_categories": [123],
            "enabled_networks": [None],
        }
    )
    assert s5.enabled_categories is None
    assert s5.enabled_networks is None


def test_flat_ips_enabled_never_becomes_dpi_enabled():
    # Flat enabled is IPS state and must never become DPI enabled
    settings = threat_management_from_controller(ips={"enabled": True, "ips_mode": "disabled"}, dpi=None)
    assert settings.enabled is False
    assert settings.traffic_identification_enabled is None
    assert settings.device_fingerprinting_enabled is None


@pytest.mark.parametrize(
    "raw_val,expected",
    [
        (True, True),
        (False, False),
        (1, None),
        (0, None),
        ("true", None),
        ("false", None),
        ([], None),
        ({}, None),
        (None, None),
    ],
)
def test_dpi_flags_strict_booleans(raw_val, expected):
    settings = threat_management_from_controller(dpi={"enabled": raw_val, "fingerprintingEnabled": raw_val})
    assert settings.traffic_identification_enabled is expected
    assert settings.device_fingerprinting_enabled is expected


def test_utm_token_and_unallowlisted_keys_excluded_even_without_redaction():
    raw_ips = {
        "_id": "603e85e1bcf86cd799439001",
        "key": "ips",
        "site_id": "default",
        "ips_mode": "ips",
        "utm_token": SECRET_TOKEN,
        "dns_filtering": True,
        "honeypot": {"enabled": False},
        "enabled_categories": ["tor"],
        "enabled_networks": ["lan"],
    }
    raw_dpi = {
        "_id": "603e85e1bcf86cd799439002",
        "key": "dpi",
        "site_id": "default",
        "enabled": True,
        "fingerprintingEnabled": True,
        "unrelated_secret": "dpi-secret-val",
    }
    settings = threat_management_from_controller(raw_ips, raw_dpi)
    dumped = settings.model_dump()

    assert set(dumped.keys()) == {
        "advanced_filtering_preference",
        "ips_mode",
        "enabled",
        "enabled_categories",
        "enabled_networks",
        "traffic_identification_enabled",
        "device_fingerprinting_enabled",
    }
    assert SECRET_TOKEN not in repr(dumped)
    assert "dpi-secret-val" not in repr(dumped)

    # Even with response redaction disabled (raw mode)
    redacted_dump = redact_sensitive_fields(dumped, redact_sensitive=False)
    assert SECRET_TOKEN not in repr(redacted_dump)
    assert "utm_token" not in redacted_dump


@pytest.mark.asyncio
async def test_system_manager_get_threat_management_settings_success():
    conn = MagicMock()
    conn.site = "default"
    mgr = SystemManager(conn)
    mgr.get_settings = AsyncMock()
    mgr.get_settings.side_effect = lambda section: {
        "ips": [
            {
                "ips_mode": "ipsInline",
                "enabled_categories": ["malware"],
                "enabled_networks": ["n1"],
                "utm_token": SECRET_TOKEN,
            }
        ],
        "dpi": [{"enabled": True, "fingerprintingEnabled": False}],
    }.get(section, [])

    result = await mgr.get_threat_management_settings()
    assert isinstance(result, ThreatManagementSettings)
    assert result.ips_mode == "ipsInline"
    assert result.enabled is True
    assert result.enabled_categories == ["malware"]
    assert result.enabled_networks == ["n1"]
    assert result.traffic_identification_enabled is True
    assert result.device_fingerprinting_enabled is False
    assert SECRET_TOKEN not in repr(result.model_dump())


@pytest.mark.asyncio
async def test_system_manager_safe_error_handling_suppresses_traceback_and_secrets(caplog):
    conn = MagicMock()
    conn.site = "default"
    mgr = SystemManager(conn)
    mgr.get_settings = AsyncMock(side_effect=AiounifiException(f"Controller failure with secret {SECRET_TOKEN}"))

    with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
        with pytest.raises(RuntimeError) as exc_info:
            await mgr.get_threat_management_settings()

    assert str(exc_info.value) == "Failed to read threat management settings"
    assert exc_info.value.__cause__ is None
    assert SECRET_TOKEN not in str(exc_info.value)
    assert SECRET_TOKEN not in caplog.text
    # Log must capture only operation context and exception class name
    assert "Failed to read threat management settings: AiounifiException" in caplog.text
