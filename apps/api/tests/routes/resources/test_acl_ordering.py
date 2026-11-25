"""REST route resolution for the Integration API ACL ordering read."""

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from unifi_core.network.managers.acl_manager import AclManager

from .test_network_misc import _bootstrap, _stub_connection


@pytest.mark.asyncio
async def test_ordering_route_is_not_shadowed_by_v2_rule_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)
    monkeypatch.setattr(AclManager, "get_acl_rule_ordering", AsyncMock(return_value=["rule-2", "rule-1"]))
    monkeypatch.setattr(
        AclManager,
        "get_acl_rule_by_id",
        AsyncMock(side_effect=AssertionError("the V2 rule detail handler was reached")),
    )

    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/v1/sites/default/acl-rules/ordering?controller={cid}", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["data"]["ordered_acl_rule_ids"] == ["rule-2", "rule-1"]
