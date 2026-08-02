"""Regression tests for Access delete and revoke preview contracts."""

import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("UNIFI_ACCESS_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_ACCESS_USERNAME", "test")
os.environ.setdefault("UNIFI_ACCESS_PASSWORD", "test")


@pytest.mark.asyncio
async def test_delete_visitor_uses_standard_delete_preview() -> None:
    with patch("unifi_access_mcp.tools.visitors.visitor_manager") as mock_manager:
        mock_manager.delete_visitor = AsyncMock(
            return_value={
                "visitor_id": "visitor-1",
                "visitor_name": "Smoke Visitor",
                "current_state": {
                    "id": "visitor-1",
                    "name": "Smoke Visitor",
                    "status": "active",
                },
                "proposed_changes": {"action": "delete"},
            }
        )
        from unifi_access_mcp.tools.visitors import access_delete_visitor

        result = await access_delete_visitor("visitor-1", confirm=False)

    assert result["success"] is True
    assert result["requires_confirmation"] is True
    assert result["action"] == "delete"
    assert result["resource_type"] == "visitor_pass"
    assert result["resource_id"] == "visitor-1"
    assert result["resource_name"] == "Smoke Visitor"
    assert result["preview"]["will_delete"] == {
        "id": "visitor-1",
        "name": "Smoke Visitor",
        "status": "active",
    }
    assert result["warnings"] == [
        "This will revoke all associated access. The controller retains the visitor as cancelled history."
    ]


@pytest.mark.asyncio
async def test_revoke_credential_preserves_revoke_action() -> None:
    with patch("unifi_access_mcp.tools.credentials.credential_manager") as mock_manager:
        mock_manager.revoke_credential = AsyncMock(
            return_value={
                "current_state": {"id": "credential-1", "type": "nfc"},
                "proposed_changes": {"action": "revoke"},
            }
        )
        from unifi_access_mcp.tools.credentials import access_revoke_credential

        result = await access_revoke_credential("credential-1", confirm=False)

    assert result["success"] is True
    assert result["requires_confirmation"] is True
    assert result["action"] == "revoke"
    assert result["resource_id"] == "credential-1"
    assert result["preview"]["proposed"] == {"action": "revoke"}
