"""Unit tests for ThreatManagementSettings API projection, routes, GraphQL, and action dispatch."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from tests.routes.resources.test_network_misc import _bootstrap, _stub_connection
from unifi_api.db.models import ApiKey, AuditLog
from unifi_api.graphql.types.network.threat_management import (
    ThreatManagementSettings as ApiThreatManagementSettings,
)
from unifi_api.services.actions import _classify_action, dispatch_action
from unifi_api.services.manifest import ManifestRegistry, ToolEntry
from unifi_core.network.managers.system_manager import SystemManager
from unifi_core.network.models.threat_management import (
    ThreatManagementSettings as CoreThreatManagementSettings,
)

SECRET_TOKEN = "synthetic-utm-token-secret-999"


def test_api_type_projection_from_core_model():
    core = CoreThreatManagementSettings(
        ips_mode="ipsInline",
        enabled=True,
        enabled_categories=["tor", "p2p"],
        enabled_networks=["lan"],
        traffic_identification_enabled=True,
        device_fingerprinting_enabled=False,
    )
    api_type = ApiThreatManagementSettings.from_manager_output(core)
    assert api_type.ips_mode == "ipsInline"
    assert api_type.enabled is True
    assert api_type.enabled_categories == ["tor", "p2p"]
    assert api_type.enabled_networks == ["lan"]
    assert api_type.traffic_identification_enabled is True
    assert api_type.device_fingerprinting_enabled is False
    assert api_type.render_hint("detail") == {"kind": "detail"}

    as_dict = api_type.to_dict()
    assert as_dict["ips_mode"] == "ipsInline"
    assert as_dict["enabled"] is True
    assert as_dict["enabled_categories"] == ["tor", "p2p"]
    assert as_dict["enabled_networks"] == ["lan"]
    assert as_dict["traffic_identification_enabled"] is True
    assert as_dict["device_fingerprinting_enabled"] is False


def test_api_type_projection_from_raw_dict_and_secret_exclusion():
    raw_dict = {
        "ips": {
            "_id": "603e85e1bcf86cd799439001",
            "ips_mode": "ids",
            "utm_token": SECRET_TOKEN,
            "enabled_categories": ["malware"],
            "enabled_networks": None,
        },
        "dpi": {
            "_id": "603e85e1bcf86cd799439002",
            "enabled": True,
            "fingerprintingEnabled": True,
            "secret_dpi": "dpi-sec",
        },
    }
    api_type = ApiThreatManagementSettings.from_manager_output(raw_dict, redact_sensitive=False)
    data = api_type.to_dict()
    assert data["ips_mode"] == "ids"
    assert data["enabled"] is True
    assert data["enabled_categories"] == ["malware"]
    assert data["enabled_networks"] is None
    assert data["traffic_identification_enabled"] is True
    assert data["device_fingerprinting_enabled"] is True
    assert SECRET_TOKEN not in repr(data)
    assert "utm_token" not in data
    assert "secret_dpi" not in data


def test_api_type_projection_from_shaped_dict():
    shaped_dict = {
        "ips_mode": "ips",
        "enabled": True,
        "enabled_categories": ["p2p"],
        "enabled_networks": ["n1"],
        "traffic_identification_enabled": False,
        "device_fingerprinting_enabled": True,
    }
    api_type = ApiThreatManagementSettings.from_manager_output(shaped_dict)
    data = api_type.to_dict()
    assert data["ips_mode"] == "ips"
    assert data["enabled"] is True
    assert data["enabled_categories"] == ["p2p"]
    assert data["enabled_networks"] == ["n1"]
    assert data["traffic_identification_enabled"] is False
    assert data["device_fingerprinting_enabled"] is True


def test_from_manager_output_flat_enabled_does_not_set_dpi():
    # Flat enabled is IPS state and must never become DPI enabled
    flat_dict = {"ips_mode": "disabled", "enabled": True}
    api_type = ApiThreatManagementSettings.from_manager_output(flat_dict)
    data = api_type.to_dict()
    assert data["enabled"] is False  # derived from ips_mode
    assert data["traffic_identification_enabled"] is None
    assert data["device_fingerprinting_enabled"] is None


def test_shaped_dict_preserves_unknown_mode_and_rejects_coerced_booleans():
    data = ApiThreatManagementSettings.from_manager_output(
        {
            "ips_mode": "future-mode",
            "enabled": "true",
            "traffic_identification_enabled": "yes",
            "device_fingerprinting_enabled": 1,
        }
    ).to_dict()
    assert data["ips_mode"] == "future-mode"
    assert data["enabled"] is None
    assert data["traffic_identification_enabled"] is None
    assert data["device_fingerprinting_enabled"] is None


def test_from_manager_output_malformed_lists_return_none():
    raw_dict = {
        "ips_mode": "ips",
        "enabled_categories": ["tor", 123, "botnet"],
        "enabled_networks": [None],
    }
    api_type = ApiThreatManagementSettings.from_manager_output(raw_dict)
    data = api_type.to_dict()
    assert data["enabled_categories"] is None
    assert data["enabled_networks"] is None


def test_action_classification():
    entry = ToolEntry(
        name="unifi_get_threat_management_settings",
        product="network",
        category="system",
        manager="system_manager",
        method="get_threat_management_settings",
        permission_action="",
        read_only_hint=True,
    )
    assert _classify_action(entry) == "read"


@pytest.mark.asyncio
async def test_action_dispatch_read_success_and_confirm_bypass():
    entry = ToolEntry(
        name="unifi_get_threat_management_settings",
        product="network",
        category="system",
        manager="system_manager",
        method="get_threat_management_settings",
        permission_action="",
        read_only_hint=True,
    )
    registry = ManifestRegistry({entry.name: entry})

    model = CoreThreatManagementSettings(
        ips_mode="ips",
        enabled=True,
        enabled_categories=["tor"],
        enabled_networks=["net1"],
        traffic_identification_enabled=True,
        device_fingerprinting_enabled=True,
    )
    manager = MagicMock()
    manager.get_threat_management_settings = AsyncMock(return_value=model)
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)

    common = dict(
        registry=registry,
        factory=factory,
        session=MagicMock(),
        tool_name=entry.name,
        controller_id="cid",
        controller_products=["network"],
        site="default",
        args={},
    )
    # Read action executes immediately even when confirm=False
    res_no_confirm = await dispatch_action(**common, confirm=False)
    assert res_no_confirm.ips_mode == "ips"
    assert res_no_confirm.enabled is True

    res_confirm = await dispatch_action(**common, confirm=True)
    assert res_confirm.ips_mode == "ips"
    assert res_confirm.enabled is True
    assert manager.get_threat_management_settings.await_count == 2


@pytest.mark.asyncio
async def test_rest_and_graphql_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    model = CoreThreatManagementSettings(
        ips_mode="ips",
        enabled=True,
        enabled_categories=["tor", "malware"],
        enabled_networks=["lan"],
        traffic_identification_enabled=True,
        device_fingerprinting_enabled=False,
    )
    monkeypatch.setattr(SystemManager, "get_threat_management_settings", AsyncMock(return_value=model))

    headers = {"Authorization": f"Bearer {key}"}
    gql_query = (
        f'{{ network {{ threatManagementSettings(controller: "{cid}") {{ '
        "ipsMode enabled enabledCategories enabledNetworks trafficIdentificationEnabled deviceFingerprintingEnabled "
        "} } }"
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        rest_resp = await client.get(
            f"/v1/sites/default/threat-management-settings?controller={cid}",
            headers=headers,
        )
        gql_resp = await client.post("/v1/graphql", headers=headers, json={"query": gql_query})

    assert rest_resp.status_code == 200
    assert gql_resp.status_code == 200

    rest_json = rest_resp.json()
    assert rest_json["render_hint"] == {"kind": "detail"}
    rest_data = rest_json["data"]
    assert rest_data["ips_mode"] == "ips"
    assert rest_data["enabled"] is True
    assert rest_data["enabled_categories"] == ["tor", "malware"]
    assert rest_data["enabled_networks"] == ["lan"]
    assert rest_data["traffic_identification_enabled"] is True
    assert rest_data["device_fingerprinting_enabled"] is False

    gql_json = gql_resp.json()
    assert "errors" not in gql_json
    gql_data = gql_json["data"]["network"]["threatManagementSettings"]
    assert gql_data["ipsMode"] == "ips"
    assert gql_data["enabled"] is True
    assert gql_data["enabledCategories"] == ["tor", "malware"]
    assert gql_data["enabledNetworks"] == ["lan"]
    assert gql_data["trafficIdentificationEnabled"] is True
    assert gql_data["deviceFingerprintingEnabled"] is False


@pytest.mark.asyncio
async def test_rest_action_http_shaping_and_failure_privacy(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    entry = ToolEntry(
        name="unifi_get_threat_management_settings",
        product="network",
        category="system",
        manager="system_manager",
        method="get_threat_management_settings",
        permission_action="",
        read_only_hint=True,
    )
    app.state.manifest_registry = ManifestRegistry({entry.name: entry})

    async with app.state.sessionmaker() as session:
        api_key = (await session.execute(select(ApiKey))).scalar_one()
        api_key.scopes = "write"
        await session.commit()

    # 1. Success action call
    mock_get_settings = AsyncMock(
        side_effect=lambda sec: (
            [{"ips_mode": "ids"}] if sec == "ips" else [{"enabled": False, "fingerprintingEnabled": False}]
        )
    )
    monkeypatch.setattr(SystemManager, "get_settings", mock_get_settings)

    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/v1/actions/unifi_get_threat_management_settings",
            headers=headers,
            json={"site": "default", "controller": cid, "args": {}},
        )
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["success"] is True
    assert res_data["render_hint"] == {"kind": "detail"}
    assert res_data["data"]["ips_mode"] == "ids"
    assert res_data["data"]["enabled"] is True

    # 2. Failure action call with sensitive controller error
    monkeypatch.setattr(
        SystemManager,
        "get_settings",
        AsyncMock(side_effect=RuntimeError(f"Network error with {SECRET_TOKEN}")),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        fail_resp = await client.post(
            "/v1/actions/unifi_get_threat_management_settings",
            headers=headers,
            json={"site": "default", "controller": cid, "args": {}},
        )
    assert fail_resp.status_code == 200
    fail_json = fail_resp.json()
    assert fail_json["success"] is False
    assert SECRET_TOKEN not in fail_resp.text

    # Audit check: verify audit row was written and contains no secret
    async with app.state.sessionmaker() as session:
        audits = (
            (await session.execute(select(AuditLog).where(AuditLog.target == "unifi_get_threat_management_settings")))
            .scalars()
            .all()
        )
    assert len(audits) == 2
    for audit in audits:
        assert SECRET_TOKEN not in repr(audit.detail)
