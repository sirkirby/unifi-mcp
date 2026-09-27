"""Fixture e2e tests for network/threat_management resolver.

# tool: unifi_get_threat_management_settings
"""

from __future__ import annotations

import pytest
from unifi_core.network.models.threat_management import ThreatManagementSettings

from tests.graphql.fixtures._helpers import (
    bootstrap,
    graphql_query,
    stub_managers,
)

SECRET_TOKEN = "synthetic-utm-token-secret-999"


@pytest.mark.asyncio
async def test_threat_management_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "system_manager", "get_threat_management_settings"): ThreatManagementSettings(
                ips_mode="ipsInline",
                enabled=True,
                enabled_categories=["tor", "malware"],
                enabled_networks=["lan-1"],
                traffic_identification_enabled=True,
                device_fingerprinting_enabled=False,
            ),
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ threatManagementSettings(controller: "{cid}") {{
            ipsMode enabled enabledCategories enabledNetworks trafficIdentificationEnabled deviceFingerprintingEnabled
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    settings = body["data"]["network"]["threatManagementSettings"]
    assert settings["ipsMode"] == "ipsInline"
    assert settings["enabled"] is True
    assert settings["enabledCategories"] == ["tor", "malware"]
    assert settings["enabledNetworks"] == ["lan-1"]
    assert settings["trafficIdentificationEnabled"] is True
    assert settings["deviceFingerprintingEnabled"] is False


@pytest.mark.asyncio
async def test_threat_management_settings_raw_dict_excludes_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "system_manager", "get_threat_management_settings"): {
                "ips": {
                    "ips_mode": "ips",
                    "utm_token": SECRET_TOKEN,
                    "enabled_categories": ["botnet"],
                    "enabled_networks": ["dmz"],
                },
                "dpi": {
                    "enabled": True,
                    "fingerprintingEnabled": True,
                },
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ threatManagementSettings(controller: "{cid}") {{
            ipsMode enabled enabledCategories enabledNetworks trafficIdentificationEnabled deviceFingerprintingEnabled
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    settings = body["data"]["network"]["threatManagementSettings"]
    assert settings["ipsMode"] == "ips"
    assert settings["enabled"] is True
    assert settings["enabledCategories"] == ["botnet"]
    assert settings["enabledNetworks"] == ["dmz"]
    assert settings["trafficIdentificationEnabled"] is True
    assert settings["deviceFingerprintingEnabled"] is True
    assert SECRET_TOKEN not in str(body)
