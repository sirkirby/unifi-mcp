"""NAT read parity across REST and GraphQL, without a controller."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiounifi.errors import LoginRequired, ResponseError
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from unifi_api.db.models import ApiKey, AuditLog
from unifi_api.services.actions import dispatch_action
from unifi_api.services.manifest import ManifestRegistry, ToolEntry
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.managers.nat_manager import NatManager

from .test_network_misc import _bootstrap, _stub_connection

RULE = {
    "_id": "nat-1",
    "type": "DNAT",
    "enabled": False,
    "rule_index": 7,
    "source_filter": {"filter_type": "NONE", "x_password": "private-value"},
    "destination_filter": {"filter_type": "ADDRESS_AND_PORT", "port": "53"},
}


@pytest.mark.asyncio
async def test_rest_and_graphql_list_detail_share_model_and_redaction(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)
    monkeypatch.setattr(NatManager, "list_nat_rules", AsyncMock(return_value=[RULE]))
    monkeypatch.setattr(NatManager, "get_nat_rule", AsyncMock(return_value=RULE))

    headers = {"Authorization": f"Bearer {key}"}
    query = (
        f'{{ network {{ natRules(controller: "{cid}") '
        "{ items { id type enabled description sourceFilter destinationFilter } } "
        f'natRule(controller: "{cid}", id: "nat-1") '
        "{ id type enabled description sourceFilter destinationFilter } "
        f'missingNat: natRule(controller: "{cid}", id: "missing") {{ id }} }} }}'
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        rest_list = await client.get(f"/v1/sites/default/nat-rules?controller={cid}", headers=headers)
        rest_detail = await client.get(f"/v1/sites/default/nat-rules/nat-1?controller={cid}", headers=headers)
        graphql = await client.post("/v1/graphql", headers=headers, json={"query": query})

    assert rest_list.status_code == rest_detail.status_code == graphql.status_code == 200
    list_rule = rest_list.json()["items"][0]
    detail_rule = rest_detail.json()["data"]
    gql = graphql.json()
    assert "errors" not in gql
    gql_list = gql["data"]["network"]["natRules"]["items"][0]
    gql_detail = gql["data"]["network"]["natRule"]
    assert gql["data"]["network"]["missingNat"] is None
    assert list_rule == detail_rule
    assert list_rule["description"] is None
    assert list_rule["enabled"] is False
    assert list_rule["source_filter"]["x_password"] == "***REDACTED***"
    assert gql_list == gql_detail
    assert gql_list["sourceFilter"] == list_rule["source_filter"]
    assert gql_list["description"] is None


@pytest.mark.asyncio
async def test_nat_rest_missing_and_controller_failure_are_value_free(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)
    secret = "private-value 192.0.2.53"
    monkeypatch.setattr(NatManager, "get_nat_rule", AsyncMock(side_effect=UniFiNotFoundError("nat_rule", secret)))
    monkeypatch.setattr(NatManager, "list_nat_rules", AsyncMock(side_effect=RuntimeError(secret)))
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.get(f"/v1/sites/default/nat-rules/missing?controller={cid}", headers=headers)
        failure = await client.get(f"/v1/sites/default/nat-rules?controller={cid}", headers=headers)
        graphql = await client.post(
            "/v1/graphql",
            headers=headers,
            json={"query": f'{{ network {{ natRules(controller: "{cid}") {{ items {{ id }} }} }} }}'},
        )
    assert missing.status_code == 404
    assert failure.status_code == 502
    assert graphql.status_code == 200
    assert secret not in missing.text + failure.text + graphql.text
    assert "RuntimeError" in failure.text


@pytest.mark.asyncio
async def test_nat_read_actions_dispatch_to_core_manager():
    from unifi_api.graphql.type_registry_init import build_type_registry
    from unifi_api.graphql.types.network.nat import NatRule as ApiNatRule

    types = build_type_registry()
    assert types.lookup_tool("unifi_list_nat_rules") == (ApiNatRule, "list")
    assert types.lookup_tool("unifi_get_nat_rule") == (ApiNatRule, "detail")
    assert ApiNatRule.from_manager_output({}).enabled is None

    manager = MagicMock()
    manager.list_nat_rules = AsyncMock(return_value=[RULE])
    manager.get_nat_rule = AsyncMock(return_value=RULE)
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)
    registry = ManifestRegistry(
        {
            name: ToolEntry(
                name=name,
                product="network",
                category="nat",
                manager="nat_manager",
                method=method,
                read_only_hint=True,
                input_schema={"type": "object", "properties": {"rule_id": {"type": "string"}}},
            )
            for name, method in (
                ("unifi_list_nat_rules", "list_nat_rules"),
                ("unifi_get_nat_rule", "get_nat_rule"),
            )
        }
    )
    common = {
        "registry": registry,
        "factory": factory,
        "session": MagicMock(),
        "controller_id": "cid",
        "controller_products": ["network"],
        "site": "default",
        "confirm": False,
    }
    assert await dispatch_action(tool_name="unifi_list_nat_rules", args={}, **common) == [RULE]
    assert await dispatch_action(tool_name="unifi_get_nat_rule", args={"rule_id": "nat-1"}, **common) == RULE
    manager.list_nat_rules.assert_awaited_once_with()
    manager.get_nat_rule.assert_awaited_once_with(rule_id="nat-1")
    assert all(call.kwargs["attr_name"] == "nat_manager" for call in factory.get_domain_manager.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("redact", [True, False])
async def test_nat_http_read_actions_project_and_follow_response_policy(tmp_path, monkeypatch, redact):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path, redact_sensitive_fields=redact)
    manager = MagicMock()
    manager.list_nat_rules = AsyncMock(return_value=[RULE])
    manager.get_nat_rule = AsyncMock(return_value=RULE)
    app.state.manager_factory.get_domain_manager = AsyncMock(return_value=manager)
    app.state.manifest_registry = ManifestRegistry(
        {
            name: ToolEntry(
                name=name,
                product="network",
                category="nat",
                manager="nat_manager",
                method=method,
                read_only_hint=True,
                input_schema={"type": "object", "properties": {"rule_id": {"type": "string"}}},
            )
            for name, method in (("unifi_list_nat_rules", "list_nat_rules"), ("unifi_get_nat_rule", "get_nat_rule"))
        }
    )
    async with app.state.sessionmaker() as session:
        api_key = (await session.execute(select(ApiKey))).scalar_one()
        api_key.scopes = "write"
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        responses = [
            await client.post(
                f"/v1/actions/{tool}",
                headers={"Authorization": f"Bearer {key}"},
                json={"site": "default", "controller": cid, "args": args},
            )
            for tool, args in (("unifi_list_nat_rules", {}), ("unifi_get_nat_rule", {"rule_id": "nat-1"}))
        ]
    assert all(response.status_code == 200 for response in responses)
    listed, detail = [response.json() for response in responses]
    assert listed["success"] is detail["success"] is True
    assert listed["data"] == [detail["data"]]
    assert listed["render_hint"]["kind"] == "list"
    assert detail["render_hint"]["kind"] == "detail"
    assert "sort_default" not in listed["render_hint"]
    assert detail["data"]["description"] is None
    expected = "***REDACTED***" if redact else "private-value"
    assert detail["data"]["source_filter"]["x_password"] == expected
    manager.list_nat_rules.assert_awaited_once_with()
    manager.get_nat_rule.assert_awaited_once_with(rule_id="nat-1")
    async with app.state.sessionmaker() as session:
        result = await session.execute(select(AuditLog).where(AuditLog.target.like("unifi_%nat_rule%")))
        audits = result.scalars().all()
    assert len(audits) == 2
    assert all(audit.outcome == "success" for audit in audits)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", ["list_failure", "get_failure", "endpoint_unavailable", "session_failure", "missing_id", "refresh_rejected"]
)
async def test_nat_http_actions_keep_controller_text_and_ids_out_of_audit(tmp_path, monkeypatch, case):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    connection = _stub_connection(app, cid)
    connection.ensure_connected = AsyncMock(return_value=True)
    connection.get_cached = MagicMock(return_value=None)
    connection.request = AsyncMock()
    connection._update_cache = MagicMock()
    secret = "synthetic-password=private 192.0.2.53"
    if case in {"list_failure", "get_failure"}:
        connection.request.side_effect = RuntimeError(secret)
    elif case == "endpoint_unavailable":
        connection.request.side_effect = ResponseError(f"Call https://{secret}/nat received 404 Not Found")
    elif case == "session_failure":
        connection.request.side_effect = LoginRequired(secret)
    else:
        connection.request.return_value = []

    entries = {
        name: ToolEntry(
            name=name,
            product="network",
            category="nat",
            manager="nat_manager",
            method=method,
            read_only_hint=True,
            input_schema={
                "type": "object",
                "properties": {"rule_id": {"type": "string"}} if method == "get_nat_rule" else {},
                "required": ["rule_id"] if method == "get_nat_rule" else [],
                "additionalProperties": False,
            },
        )
        for name, method in (("unifi_list_nat_rules", "list_nat_rules"), ("unifi_get_nat_rule", "get_nat_rule"))
    }
    app.state.manifest_registry = ManifestRegistry(entries)
    async with app.state.sessionmaker() as session:
        api_key = (await session.execute(select(ApiKey))).scalar_one()
        api_key.scopes = "write"
        await session.commit()

    tool = "unifi_get_nat_rule" if case in {"get_failure", "missing_id", "refresh_rejected"} else "unifi_list_nat_rules"
    args = {"rule_id": secret} if tool == "unifi_get_nat_rule" else {}
    if case == "refresh_rejected":
        args["refresh"] = True
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/actions/{tool}",
            headers={"Authorization": f"Bearer {key}"},
            json={"site": "default", "controller": cid, "args": args},
        )
    assert response.status_code == 200
    assert response.json()["success"] is False
    assert secret not in response.text
    async with app.state.sessionmaker() as session:
        audit = (await session.execute(select(AuditLog).where(AuditLog.target == tool))).scalar_one()
    assert secret not in (audit.detail or "")
    if case in {"list_failure", "get_failure"}:
        assert "RuntimeError" in audit.detail
        assert "Check the controller connection and NAT support" in audit.detail
    elif case == "endpoint_unavailable":
        assert "Network 9.0+" in audit.detail
        assert "UniFi gateway" in audit.detail
    elif case == "session_failure":
        assert audit.error_kind == "LoginRequired"
        assert "Check Network session access and permissions" in audit.detail
    elif case == "missing_id":
        assert audit.error_kind == "UniFiNotFoundError"
        assert audit.detail == "NAT rule not found"
    else:
        connection.request.assert_not_awaited()
        assert "refresh" in audit.detail
