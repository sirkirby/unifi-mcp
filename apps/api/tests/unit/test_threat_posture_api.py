"""Typed REST, GraphQL, and action exposure for Core threat posture."""

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from tests.routes.resources.test_network_misc import _bootstrap, _stub_connection
from unifi_api.db.models import ApiKey
from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.network.threat_posture import ThreatPosture as ApiThreatPosture
from unifi_api.services.manifest import ManifestRegistry, ToolEntry
from unifi_core.network.managers.system_manager import SystemManager
from unifi_core.network.models.threat_posture import threat_posture_from_controller

_BIG = 2**40
_TIMESTAMP_MS = 1786225096952


def _posture(period="DAY", threats=3):
    return threat_posture_from_controller(
        period,
        {
            "enterprise": True,
            "has_subscription": None,
            "ips_enabled": False,
            "is_activating": None,
            "scanned_bytes": _BIG,
            "signature_capacity": _BIG,
            "signatures": _BIG,
            "threats": threats,
            "updated_timestamp": _TIMESTAMP_MS,
            "controller_token": "secret-token",
        },
        [
            {
                "_id": "legacy-device-1",
                "mac": "aa:bb:cc:dd:ee:ff",
                "name": "Gateway",
                "controller_token": "secret-token",
                "ids_ips_signature": {
                    "rule_count": _BIG,
                    "update_time": _TIMESTAMP_MS,
                    "signature_type": "ids",
                    "is_activating": False,
                    "sha_256": "secret-hash",
                },
            }
        ],
    )


def test_type_projection_and_rest_schema_exclude_raw_extras():
    data = ApiThreatPosture.from_manager_output(_posture(), redact_sensitive=False).to_dict()
    assert data["scanned_bytes"] == _BIG
    assert data["updated_timestamp"] == _TIMESTAMP_MS
    assert data["has_subscription"] is None
    assert data["gateway_signatures"][0]["rule_count"] == _BIG
    assert data["gateway_signatures"][0]["update_time"] == _TIMESTAMP_MS
    assert "secret-token" not in repr(data)
    assert "secret-hash" not in repr(data)
    assert to_pydantic_model(ApiThreatPosture).model_fields["scanned_bytes"].annotation == int | None


@pytest.mark.asyncio
async def test_rest_graphql_and_action_parity(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)
    model = _posture()
    manager_read = AsyncMock(return_value=model)
    monkeypatch.setattr(SystemManager, "get_threat_posture", manager_read)
    entry = ToolEntry(
        name="unifi_get_threat_posture",
        product="network",
        category="system",
        manager="system_manager",
        method="get_threat_posture",
        permission_action="",
        read_only_hint=True,
        input_schema={"type": "object", "properties": {"period": {"type": "string"}}},
    )
    app.state.manifest_registry = ManifestRegistry({entry.name: entry})
    async with app.state.sessionmaker() as session:
        api_key = (await session.execute(select(ApiKey))).scalar_one()
        api_key.scopes = "read,write"
        await session.commit()

    headers = {"Authorization": f"Bearer {key}"}
    query = (
        f'{{ network {{ threatPosture(controller: "{cid}", period: "DAY") {{ '
        "period enterprise hasSubscription ipsEnabled isActivating scannedBytes signatureCapacity "
        "signatures threats updatedTimestamp gatewaySignatures { deviceId macAddress name ruleCount "
        "updateTime signatureType isActivating } } } }"
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        rest = await client.get(f"/v1/sites/default/threat-posture?controller={cid}&period=DAY", headers=headers)
        gql = await client.post("/v1/graphql", headers=headers, json={"query": query})
        action = await client.post(
            "/v1/actions/unifi_get_threat_posture",
            headers=headers,
            json={"site": "default", "controller": cid, "args": {"period": "DAY"}},
        )
    assert rest.status_code == gql.status_code == action.status_code == 200
    assert "errors" not in gql.json()
    rest_data = rest.json()["data"]
    action_data = action.json()["data"]
    assert rest_data == action_data
    assert rest_data == ApiThreatPosture.from_manager_output(model).to_dict()
    gql_data = gql.json()["data"]["network"]["threatPosture"]
    assert gql_data["scannedBytes"] == rest_data["scanned_bytes"] == _BIG
    assert gql_data["updatedTimestamp"] == rest_data["updated_timestamp"] == _TIMESTAMP_MS
    assert gql_data["gatewaySignatures"][0]["ruleCount"] == _BIG
    assert gql_data["gatewaySignatures"][0]["updateTime"] == _TIMESTAMP_MS
    assert gql_data["gatewaySignatures"][0]["deviceId"] == "legacy-device-1"
    assert "secret-token" not in repr((rest.json(), gql.json(), action.json()))
    assert "secret-hash" not in repr((rest.json(), gql.json(), action.json()))
    assert manager_read.await_count == 3


@pytest.mark.asyncio
async def test_graphql_cache_separates_periods(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def read_period(period="DAY"):
        return _posture(period, threats=1 if period == "HOUR" else 7)

    manager_read = AsyncMock(side_effect=read_period)
    monkeypatch.setattr(SystemManager, "get_threat_posture", manager_read)
    query = (
        f'{{ network {{ hour: threatPosture(controller: "{cid}", period: "HOUR") {{ period threats }} '
        f'day: threatPosture(controller: "{cid}", period: "DAY") {{ period threats }} }} }}'
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/graphql", headers={"Authorization": f"Bearer {key}"}, json={"query": query})
    assert response.status_code == 200
    assert "errors" not in response.json()
    data = response.json()["data"]["network"]
    assert data["hour"] == {"period": "HOUR", "threats": 1}
    assert data["day"] == {"period": "DAY", "threats": 7}
    assert manager_read.await_count == 2


@pytest.mark.asyncio
async def test_rest_invalid_period_maps_core_validation_to_422(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)
    read = AsyncMock(side_effect=ValueError("Invalid threat posture period"))
    monkeypatch.setattr(SystemManager, "get_threat_posture", read)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/sites/default/threat-posture?controller={cid}&period=YEAR",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert response.status_code == 422
    read.assert_awaited_once_with(period="YEAR")
