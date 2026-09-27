"""NAT API actions dispatch to verified Core methods and keep audit value-free."""

from pathlib import Path
from runpy import run_path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiounifi.errors import ResponseError
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from unifi_api.db.models import ApiKey, AuditLog
from unifi_api.services.actions import MutationPreview, dispatch_action
from unifi_api.services.manifest import ManifestRegistry, ToolEntry
from unifi_core.network.models.nat import NatCreateToolInput, nat_write_input_schema
from unifi_core.write_verification import failed_write

from .test_network_misc import _bootstrap, _stub_connection


def _entry(name: str, method: str, action: str, properties: dict, required: list[str]) -> ToolEntry:
    return ToolEntry(
        name=name,
        product="network",
        category="nat",
        manager="nat_manager",
        method=method,
        permission_action=action,
        read_only_hint=False,
        input_schema={"type": "object", "properties": properties, "required": required, "additionalProperties": False},
    )


_SCHEMA = nat_write_input_schema()
CREATE = _entry("unifi_create_nat_rule", "create_nat_rule_verified", "create", {"rule_data": _SCHEMA}, ["rule_data"])
UPDATE = _entry(
    "unifi_update_nat_rule",
    "update_nat_rule_verified",
    "update",
    {"rule_id": {"type": "string"}, "update_data": _SCHEMA},
    ["rule_id", "update_data"],
)
DELETE = _entry(
    "unifi_delete_nat_rule", "delete_nat_rule_verified", "delete", {"rule_id": {"type": "string"}}, ["rule_id"]
)
TOGGLE = _entry(
    "unifi_toggle_nat_rule",
    "toggle_nat_rule_verified",
    "update",
    {"rule_id": {"type": "string"}, "enabled": {"type": "boolean"}},
    ["rule_id", "enabled"],
)


def test_api_catalog_projection_preserves_model_derived_nested_schema():
    generator = Path(__file__).resolve().parents[5] / "scripts/generate_api_action_catalog.py"
    _api_input_schema = run_path(str(generator))["_api_input_schema"]
    tool = {"schema": {"input": nat_write_input_schema(NatCreateToolInput)}}
    schema = _api_input_schema(tool, product="network", name=CREATE.name, path=Path("tools_manifest.json"))
    assert "confirm" not in schema["properties"]
    nested = schema["properties"]["rule_data"]["properties"]["destination_filter"]["anyOf"][0]
    assert nested["additionalProperties"] is False


@pytest.mark.asyncio
async def test_dispatch_preview_is_partial_and_confirm_uses_verified_core():
    manager = MagicMock()
    manager.create_nat_rule_verified = AsyncMock(return_value=failed_write("rejected", operation="create"))
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)
    registry = ManifestRegistry({CREATE.name: CREATE})
    common = dict(
        registry=registry,
        factory=factory,
        session=MagicMock(),
        tool_name=CREATE.name,
        controller_id="c",
        controller_products=["network"],
        site="default",
        args={"rule_data": {"type": "MASQUERADE", "out_interface": "net-1"}},
    )
    preview = await dispatch_action(**common, confirm=False)
    assert isinstance(preview, MutationPreview)
    assert preview.payload["preview"]["will_create"]["rule_data"]["enabled"] is False
    factory.get_domain_manager.assert_not_awaited()
    result = await dispatch_action(**common, confirm=True)
    assert result.success is False and result.mutation_applied is False
    manager.create_nat_rule_verified.assert_awaited_once_with(
        rule_data={"type": "MASQUERADE", "out_interface": "net-1", "enabled": False}
    )


@pytest.mark.asyncio
async def test_api_rejects_nested_typo_before_manager_with_value_free_message():
    factory = MagicMock()
    registry = ManifestRegistry({UPDATE.name: UPDATE})
    with pytest.raises(ValueError) as error:
        await dispatch_action(
            registry=registry,
            factory=factory,
            session=MagicMock(),
            tool_name=UPDATE.name,
            controller_id="c",
            controller_products=["network"],
            site="default",
            args={"rule_id": "nat-1", "update_data": {"destination_filter": {"adress": "private-value"}}},
            confirm=True,
        )
    assert "private-value" not in str(error.value)
    factory.get_domain_manager.assert_not_called()


@pytest.mark.asyncio
async def test_http_controller_rejection_and_audit_contain_no_controller_values(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    connection = _stub_connection(app, cid)
    connection.ensure_connected = AsyncMock(return_value=True)
    connection.get_cached = MagicMock(return_value=None)
    connection._update_cache = MagicMock()
    connection._invalidate_cache = MagicMock()
    secret = "private-value 192.0.2.53"
    connection.request = AsyncMock(side_effect=ResponseError(f"Call https://{secret}/nat received 409 Conflict"))
    app.state.manifest_registry = ManifestRegistry({CREATE.name: CREATE})
    async with app.state.sessionmaker() as session:
        api_key = (await session.execute(select(ApiKey))).scalar_one()
        api_key.scopes = "write"
        await session.commit()
    args = {
        "rule_data": {
            "type": "MASQUERADE",
            "out_interface": "net-1",
            "rule_index": 1,
            "description": secret,
        }
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/actions/{CREATE.name}",
            headers={"Authorization": f"Bearer {key}"},
            json={"site": "default", "controller": cid, "args": args, "confirm": True},
        )
    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["mutation_applied"] is False
    assert secret not in response.text
    async with app.state.sessionmaker() as session:
        audit = (await session.execute(select(AuditLog).where(AuditLog.target == CREATE.name))).scalar_one()
    assert secret not in (audit.detail or "")
    assert audit.outcome == "error"
    connection.request.assert_awaited_once()


@pytest.mark.asyncio
async def test_http_nested_unknown_key_never_enters_audit(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)
    app.state.manifest_registry = ManifestRegistry({UPDATE.name: UPDATE})
    async with app.state.sessionmaker() as session:
        api_key = (await session.execute(select(ApiKey))).scalar_one()
        api_key.scopes = "write"
        await session.commit()
    secret = "private-value-192.0.2.53"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/actions/{UPDATE.name}",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "site": "default",
                "controller": cid,
                "confirm": True,
                "args": {"rule_id": "nat-1", "update_data": {"destination_filter": {secret: "x"}}},
            },
        )
    assert response.json()["success"] is False
    assert secret not in response.text
    async with app.state.sessionmaker() as session:
        audit = (await session.execute(select(AuditLog).where(AuditLog.target == UPDATE.name))).scalar_one()
    assert secret not in (audit.detail or "")
